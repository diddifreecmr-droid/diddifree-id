"""Mint a `role=service` access token for a backend module.

The mechanism for service-to-service auth is still open (contract §5), so this
covers the JWT half of the two options implemented in `core.auth_deps`. It is an
operator tool, run by hand against the production key material — which is why it
lives in `scripts/` and is not reachable over HTTP.

    python scripts/issue_service_token.py --service diddi-wallet --hours 24

Prefer short lifetimes and re-issue on a schedule: a service token has no
`refresh` flow and no revocation list, so its expiry is the only thing that ever
takes it out of circulation.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import jwt

from identity_app.core.keys import get_key_ring
from identity_app.core.settings import settings


def issue(service_name: str, hours: int) -> str:
    key_ring = get_key_ring()
    now = datetime.now(UTC)
    # A stable, derived `sub` so logs and traces can tell which service acted,
    # without inventing a user row that does not exist.
    subject = uuid5(NAMESPACE_URL, f"urn:diddifree:service:{service_name}")
    payload = {
        "sub": str(subject),
        "role": "service",
        "status": "active",
        "service": service_name,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(hours=hours),
    }
    return jwt.encode(
        payload,
        key_ring.private_pem,
        algorithm="RS256",
        headers={"kid": key_ring.active_kid},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, help="ex. diddi-wallet, diddi-go, diddi-fund")
    parser.add_argument("--hours", type=int, default=24, help="durée de validité (défaut : 24 h)")
    args = parser.parse_args()

    print(issue(args.service, args.hours))


if __name__ == "__main__":
    main()
