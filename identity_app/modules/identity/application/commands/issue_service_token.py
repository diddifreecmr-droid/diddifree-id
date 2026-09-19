"""OAuth-like client-credentials issuance for backend services."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from identity_app.core.errors import ApiError
from identity_app.core.settings import settings
from identity_app.modules.identity.domain.interfaces import ServiceClientRepository
from identity_app.modules.identity.infra.token_service import TokenService


@dataclass
class IssueServiceToken:
    clients: ServiceClientRepository
    tokens: TokenService

    async def __call__(
        self,
        *,
        grant_type: str,
        client_id: str,
        client_secret: str,
        audience: str,
        scope: str,
    ) -> dict:
        if grant_type != "client_credentials":
            raise ApiError(400, "UNSUPPORTED_GRANT_TYPE", "Seul le grant_type client_credentials est accepté.")

        client = await self.clients.find_by_client_id(client_id.strip())
        if not client or not _secret_matches(client_secret, client.secret_hash):
            # Do not reveal whether the id exists, is disabled, or has a wrong secret.
            raise ApiError(401, "INVALID_CLIENT", "Identifiants service invalides.")

        now = datetime.now(UTC)
        if not client.active or client.revoked_at is not None or (
            client.expires_at is not None and client.expires_at <= now
        ):
            raise ApiError(401, "INVALID_CLIENT", "Identifiants service invalides.")

        audience = audience.strip()
        requested_scopes = tuple(dict.fromkeys(part for part in scope.split() if part))
        if not audience or audience not in client.allowed_audiences:
            raise ApiError(403, "INVALID_AUDIENCE", "Audience non autorisée pour ce client.")
        if not requested_scopes or not set(requested_scopes).issubset(client.allowed_scopes):
            raise ApiError(403, "INVALID_SCOPE", "Scope non autorisé pour ce client.")

        expires_in = settings.service_token_lifetime_seconds
        token = self.tokens.issue_service_token(
            service_name=client.service_name,
            client_id=client.client_id,
            audience=audience,
            scopes=requested_scopes,
            lifetime_seconds=expires_in,
        )
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": " ".join(requested_scopes),
        }


def _secret_matches(raw_secret: str, expected_hash: str) -> bool:
    return hmac.compare_digest(sha256(raw_secret.encode()).hexdigest(), expected_hash)
