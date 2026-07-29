"""`GET /.well-known/jwks.json` — the single most-consumed endpoint here.

Every module in the ecosystem polls it, and every module's ability to
authenticate anyone depends on it answering. It reads from the in-process key
ring, touches neither PostgreSQL nor Redis, and so keeps working during a
database incident — which is exactly when you want token verification to remain
unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass

from identity_app.modules.identity.infra.token_service import TokenService


@dataclass
class GetJwks:
    tokens: TokenService

    async def __call__(self) -> dict:
        return self.tokens.jwks()
