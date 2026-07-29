"""One-shot migration: DiddiGo `auth.users` → DiddiFreeID `identity.users`.

Step 2 of architecture §7. The single non-negotiable rule is at the top of that
section: **ids are preserved**. `ride.rides.passenger_id`, `driver_profiles` and
anything else on the DiddiGo side already reference those UUIDs, and a migration
that reassigned them would leave every existing ride pointing at nobody.

Run it early, while DiddiGo's table is still small — the doc says so, and it is
right: the first run is where the role mapping and the duplicate handling get
argued about, and that argument is cheaper over fifty rows than fifty thousand.

    python scripts/migrate_from_diddigo.py --dry-run
    python scripts/migrate_from_diddigo.py

Idempotent: a user already present in `identity.users` (by id or by phone) is
reported and skipped, never overwritten. Re-running after fixing a conflict is
therefore safe.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import psycopg

DEFAULT_SOURCE = "postgresql://postgres:postgres@localhost:5433/diddi_go"
DEFAULT_TARGET = "postgresql://postgres:postgres@localhost:5435/diddi_free_id"

# DiddiGo calls its baseline role `passenger`; the ecosystem-wide vocabulary is
# `user`, because the same account also shops, funds and learns. Anything not
# listed here stops the migration rather than being guessed at — a silently
# mistranslated role is an authorisation bug waiting to happen.
ROLE_MAP = {
    "passenger": "user",
    "driver": "driver",
    "admin": "admin",
}

STATUS_MAP = {
    "active": "active",
    "suspended": "suspended",
    "pending_verification": "pending_verification",
}


@dataclass
class Report:
    migrated: int = 0
    skipped_existing_id: list[str] = field(default_factory=list)
    skipped_phone_taken: list[str] = field(default_factory=list)
    unknown_role: list[str] = field(default_factory=list)
    unknown_status: list[str] = field(default_factory=list)

    def print(self, *, dry_run: bool) -> None:
        verb = "à migrer" if dry_run else "migrés"
        print(f"\n{self.migrated} compte(s) {verb}.")
        for label, rows in (
            ("déjà présents (même id)", self.skipped_existing_id),
            ("ignorés — téléphone déjà pris par un autre id", self.skipped_phone_taken),
            ("rôle inconnu", self.unknown_role),
            ("statut inconnu", self.unknown_status),
        ):
            if rows:
                print(f"\n{len(rows)} {label} :")
                for row in rows:
                    print(f"  - {row}")

    @property
    def has_blocking_issues(self) -> bool:
        return bool(self.unknown_role or self.unknown_status or self.skipped_phone_taken)


def migrate(source_dsn: str, target_dsn: str, *, dry_run: bool) -> Report:
    report = Report()

    with psycopg.connect(source_dsn) as source, source.cursor() as cur:
        cur.execute(
            "SELECT id, phone, full_name, password_hash, role, status, created_at, updated_at "
            "FROM auth.users ORDER BY created_at",
        )
        rows = cur.fetchall()

    print(f"{len(rows)} compte(s) trouvé(s) dans DiddiGo (auth.users).")

    with psycopg.connect(target_dsn) as target, target.cursor() as cur:
        for (user_id, phone, full_name, password_hash, role, status, created_at, updated_at) in rows:
            mapped_role = ROLE_MAP.get(role)
            if mapped_role is None:
                report.unknown_role.append(f"{phone} (id={user_id}) : rôle {role!r}")
                continue

            mapped_status = STATUS_MAP.get(status)
            if mapped_status is None:
                report.unknown_status.append(f"{phone} (id={user_id}) : statut {status!r}")
                continue

            cur.execute("SELECT 1 FROM identity.users WHERE id = %s", (user_id,))
            if cur.fetchone():
                report.skipped_existing_id.append(f"{phone} (id={user_id})")
                continue

            # A phone belonging to a *different* id is the one case needing a
            # human: two accounts for the same person, and only the business
            # can say which one survives.
            cur.execute("SELECT id FROM identity.users WHERE phone = %s", (phone,))
            clash = cur.fetchone()
            if clash:
                report.skipped_phone_taken.append(
                    f"{phone} : DiddiGo id={user_id} vs DiddiFreeID id={clash[0]}",
                )
                continue

            if not dry_run:
                cur.execute(
                    "INSERT INTO identity.users "
                    "(id, phone, full_name, password_hash, role, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        user_id,
                        phone,
                        full_name,
                        password_hash,
                        mapped_role,
                        mapped_status,
                        created_at,
                        updated_at,
                    ),
                )
            report.migrated += 1

        if dry_run:
            target.rollback()
        else:
            target.commit()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dsn", default=DEFAULT_SOURCE, help="DiddiGo (lecture seule)")
    parser.add_argument("--target-dsn", default=DEFAULT_TARGET, help="DiddiFreeID")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="tout analyser et n'écrire rien — à lancer en premier, systématiquement",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("MODE SIMULATION — aucune écriture ne sera conservée.\n")

    report = migrate(args.source_dsn, args.target_dsn, dry_run=args.dry_run)
    report.print(dry_run=args.dry_run)

    if report.has_blocking_issues:
        print(
            "\nDes cas nécessitent un arbitrage avant la bascule (étape 3 de la section 7). "
            "Les comptes concernés n'ont PAS été migrés.",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
