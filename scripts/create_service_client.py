"""Create a machine client and print its secret once.

Example for staging:
    python scripts/create_service_client.py --client-id pilotage-staging-diddigo \
      --service pilotage --environment staging --audience diddigo \
      --scope ride-summary:read

The generated secret is not recoverable from DiddiFreeID. Put it in the
consumer's secret store immediately and never commit it.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from identity_app.core.database import async_session_factory, engine
from identity_app.modules.identity.infra.models import ServiceClientModel


async def create_client(
    *,
    client_id: str,
    service_name: str,
    environment: str,
    audiences: list[str],
    scopes: list[str],
) -> str:
    secret = token_urlsafe(32)
    async with async_session_factory() as session:
        session.add(
            ServiceClientModel(
                id=uuid4(),
                client_id=client_id,
                service_name=service_name,
                environment=environment,
                secret_hash=sha256(secret.encode()).hexdigest(),
                allowed_audiences=audiences,
                allowed_scopes=scopes,
            ),
        )
        await session.commit()
    return secret


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--service", required=True, dest="service_name")
    parser.add_argument("--environment", required=True, choices=("development", "staging", "production"))
    parser.add_argument("--audience", required=True, action="append")
    parser.add_argument("--scope", required=True, action="append")
    args = parser.parse_args()

    secret = await create_client(
        client_id=args.client_id,
        service_name=args.service_name,
        environment=args.environment,
        audiences=args.audience,
        scopes=args.scope,
    )
    print(f"client_id={args.client_id}")
    print(f"client_secret={secret}")
    await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
