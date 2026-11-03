"""Create an isolated Google Play Review account.

The account is active and marked as a Review account from its creation, so it
can use the fixed six-digit code configured separately in Portainer. This
script deliberately never accepts, prints or stores that code: after it
prints ``review_user_id``, add the code under that UUID in
``REVIEW_STATIC_OTP_CODES_JSON`` and redeploy the stack.

Example (inside the app container):

    python scripts/create_review_account.py \
      --email google-reviewer@example.com --name "Google Play reviewer"
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from identity_app.core.database import async_session_factory, engine
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.infra.models import UserModel

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise SystemExit("Adresse e-mail invalide.")
    return normalized


async def _create(args: argparse.Namespace) -> str:
    phone = validate_phone(args.phone) if args.phone else None
    email = _validate_email(args.email)
    if phone is None and email is None:
        raise SystemExit("Fournissez --phone ou --email.")

    async with async_session_factory() as session:
        if phone is not None and await session.scalar(select(UserModel.id).where(UserModel.phone == phone)):
            raise SystemExit("Ce numéro appartient déjà à un compte. Utilisez la route admin auditée pour le modifier.")
        if email is not None and await session.scalar(select(UserModel.id).where(UserModel.email == email)):
            raise SystemExit(
                "Cette adresse e-mail appartient déjà à un compte. "
                "Utilisez la route admin auditée pour le modifier.",
            )

        user = UserModel(
            phone=phone,
            email=email,
            full_name=args.name,
            language="fr",
            role="user",
            status="active",
            is_review_account=True,
        )
        session.add(user)
        await session.commit()
        return str(user.id)


async def _run(args: argparse.Namespace) -> None:
    try:
        user_id = await _create(args)
        print(f"review_user_id={user_id}")
        print("Ajoutez ce user_id avec un code à six chiffres dans REVIEW_STATIC_OTP_CODES_JSON via Portainer.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", help="Numéro E.164 du compte Review")
    parser.add_argument("--email", help="Adresse e-mail du compte Review")
    parser.add_argument("--name", default="Google Play Review", help="Nom affiché")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
