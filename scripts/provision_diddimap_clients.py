"""Provision the DiddiMap service clients used by the DiddiFree ecosystem.

Run from the repository root, against the target database:

    python scripts/provision_diddimap_clients.py --environment staging

The command is safe to re-run. New clients print their secret once. Existing
client secrets are never displayed, regenerated, or stored in this repository.
Use the admin secret-rotation endpoint when an existing secret is unavailable.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import select

from identity_app.core.database import async_session_factory, engine
from identity_app.modules.identity.infra.models import ServiceClientModel


@dataclass(frozen=True)
class DiddiMapClientSpec:
    service_name: str
    scopes: tuple[str, ...]

    def client_id(self, environment: str) -> str:
        return f"{self.service_name}-{environment}-diddimap"


DIDDIMAP_CLIENTS: tuple[DiddiMapClientSpec, ...] = (
    DiddiMapClientSpec(
        service_name="diddigo",
        scopes=(
            "diddimap:routing:read",
            "diddimap:geocoding:read",
            "diddimap:traces:write",
        ),
    ),
    DiddiMapClientSpec(
        service_name="diddisend",
        scopes=(
            "diddimap:routing:read",
            "diddimap:geocoding:read",
        ),
    ),
    DiddiMapClientSpec(
        service_name="backoffice",
        scopes=(
            "diddimap:reports:read",
            "diddimap:reports:decide",
            "diddimap:insights:read",
            "diddimap:insights:decide",
        ),
    ),
    DiddiMapClientSpec(
        service_name="pilotage",
        scopes=("diddimap:pilotage:read",),
    ),
)


async def provision_clients(*, environment: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    async with async_session_factory() as session:
        for spec in DIDDIMAP_CLIENTS:
            client_id = spec.client_id(environment)
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
                        service_name=spec.service_name,
                        environment=environment,
                        secret_hash=sha256(secret.encode()).hexdigest(),
                        allowed_audiences=["diddimap"],
                        allowed_scopes=list(spec.scopes),
                    ),
                )
                results.append(
                    {
                        "client_id": client_id,
                        "status": "created",
                        "client_secret": secret,
                    },
                )
                continue

            if client.service_name != spec.service_name or client.environment != environment:
                raise RuntimeError(
                    f"Client {client_id} existe avec un service ou environnement incompatible."
                )
            client.allowed_audiences = ["diddimap"]
            client.allowed_scopes = list(spec.scopes)
            results.append(
                {
                    "client_id": client_id,
                    "status": "updated_policy_secret_unchanged",
                },
            )
        await session.commit()
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment",
        required=True,
        choices=("development", "staging", "production"),
    )
    args = parser.parse_args()

    try:
        for result in await provision_clients(environment=args.environment):
            print(f"client_id={result['client_id']}")
            print(f"status={result['status']}")
            if "client_secret" in result:
                print(f"client_secret={result['client_secret']}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
