"""Provision the DiddiAdmin to DiddiSupport machine client.

Run from the repository root against the target DiddiFreeID database:

    python scripts/provision_diddiadmin_diddisupport_client.py --environment staging

The command is safe to re-run. It creates the client once and prints its
secret only at that point. Existing secrets are neither printed nor rotated.
Store a newly printed secret directly in DiddiAdmin's secret manager.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import select

from identity_app.core.database import async_session_factory, engine
from identity_app.modules.identity.infra.models import ServiceClientModel


SERVICE_NAME = "diddiadmin"
TARGET_AUDIENCE = "diddi-support"
SCOPES = (
    "diddi-support:read",
    "diddi-support:write",
)


def client_id_for(environment: str) -> str:
    # The client ID keeps the Backoffice naming convention, while the JWT
    # service identity remains `diddiadmin` for the receiving service.
    return f"backoffice-{environment}-diddisupport"


async def provision_client(*, environment: str) -> dict[str, str]:
    """Create the client or align its policy without rotating its secret."""
    client_id = client_id_for(environment)
    async with async_session_factory() as session:
        result = await session.execute(
            select(ServiceClientModel).where(ServiceClientModel.client_id == client_id),
        )
        client = result.scalar_one_or_none()
        if client is None:
            secret = token_urlsafe(32)
            session.add(
                ServiceClientModel(
                    id=uuid4(),
                    client_id=client_id,
                    service_name=SERVICE_NAME,
                    environment=environment,
                    secret_hash=sha256(secret.encode()).hexdigest(),
                    allowed_audiences=[TARGET_AUDIENCE],
                    allowed_scopes=list(SCOPES),
                ),
            )
            await session.commit()
            return {
                "client_id": client_id,
                "status": "created",
                "client_secret": secret,
            }

        if client.service_name != SERVICE_NAME or client.environment != environment:
            raise RuntimeError(
                f"Client {client_id} existe avec un service ou environnement incompatible.",
            )
        client.allowed_audiences = [TARGET_AUDIENCE]
        client.allowed_scopes = list(SCOPES)
        client.active = True
        client.revoked_at = None
        await session.commit()
        return {
            "client_id": client_id,
            "status": "updated_policy_secret_unchanged",
        }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment",
        required=True,
        choices=("development", "staging", "production"),
    )
    args = parser.parse_args()

    try:
        result = await provision_client(environment=args.environment)
        print(f"client_id={result['client_id']}")
        print(f"status={result['status']}")
        if "client_secret" in result:
            print(f"client_secret={result['client_secret']}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
