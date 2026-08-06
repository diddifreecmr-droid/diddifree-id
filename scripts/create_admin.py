"""Create or explicitly promote an administrator and print an access token.

Run locally or inside the running app container, where the database and the
RS256 signing keys are available:

    python scripts/create_admin.py --phone +2250700000000 \
        --email admin@example.com --name "DiddiFree Admin"

An existing non-admin account requires ``--promote-existing``. The token is
printed once to stdout and is never stored in the database or repository.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

# When invoked as `python scripts/create_admin.py`, Python puts `scripts/`
# rather than the project root on sys.path. Add the root so the same command
# works locally and from `/app` in the Docker image.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from identity_app.core.database import async_session_factory, engine
from identity_app.core.settings import settings
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.infra.models import UserModel
from identity_app.modules.identity.infra.token_service import TokenService

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise SystemExit("Adresse e-mail invalide.")
    return normalized


async def _create_or_promote(args: argparse.Namespace) -> tuple[UUID, bool]:
    phone = validate_phone(args.phone)
    email = _validate_email(args.email)

    async with async_session_factory() as session:
        user = await session.scalar(select(UserModel).where(UserModel.phone == phone))
        if user is not None and user.role != "admin" and not args.promote_existing:
            raise SystemExit(
                "Un utilisateur existe déjà pour ce numéro. "
                "Ajoutez --promote-existing pour le promouvoir explicitement.",
            )

        if email is not None:
            email_owner = await session.scalar(select(UserModel).where(UserModel.email == email))
            if email_owner is not None and (user is None or email_owner.id != user.id):
                raise SystemExit("Cette adresse e-mail appartient déjà à un autre utilisateur.")

        created = user is None
        if user is None:
            user = UserModel(
                phone=phone,
                email=email,
                full_name=args.name,
                language="fr",
                role="admin",
                status="active",
            )
            session.add(user)
        else:
            user.role = "admin"
            user.status = "active"
            if email is not None:
                user.email = email
            if args.name:
                user.full_name = args.name

        await session.commit()
        return user.id, created


async def _run(args: argparse.Namespace) -> None:
    try:
        user_id, created = await _create_or_promote(args)
        token = TokenService().issue_access_token(
            user_id=user_id,
            role="admin",
            status="active",
            lifetime_minutes=args.minutes,
        )
        print(f"admin_user_id={user_id}")
        print(f"admin_user_action={'created' if created else 'promoted'}")
        print(f"admin_token={token}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True, help="Numéro E.164 de l'administrateur")
    parser.add_argument("--email", help="Adresse e-mail de l'administrateur")
    parser.add_argument("--name", default="DiddiFree Admin", help="Nom affiché")
    parser.add_argument(
        "--promote-existing",
        action="store_true",
        help="autoriser explicitement la promotion d'un utilisateur existant",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=settings.jwt_access_lifetime_minutes,
        help="durée du token (défaut: configuration, maximum: 1440 minutes)",
    )
    args = parser.parse_args()
    if not 1 <= args.minutes <= 1440:
        parser.error("--minutes doit être compris entre 1 et 1440.")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
