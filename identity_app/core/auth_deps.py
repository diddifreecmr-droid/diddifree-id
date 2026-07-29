"""Authentication and authorisation dependencies.

DiddiFreeID verifies its own tokens exactly the way every consuming module does
— signature, `kid`, issuer, expiry — and nothing else. No database round-trip on
the normal path: the whole architecture rests on a token being self-sufficient,
and this service contradicting that would be a strange thing to explain.

Privileged routes are the exception, and deliberately so: `require_admin` reads
the account fresh. A 15-minute-old token claiming `role=admin` is fine for
reading one's own profile, and not fine for suspending someone else's account
after that admin has just been demoted.
"""

# NOTE: no `from __future__ import annotations` — see the note in `core.deps`.

from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from identity_app.core.deps import get_token_service, user_read_repo
from identity_app.core.errors import ApiError
from identity_app.core.settings import settings
from identity_app.modules.identity.domain.entities import (
    SESSION_ALLOWED_STATUSES,
    User,
    UserRole,
    UserStatus,
)
from identity_app.modules.identity.infra.read_repository import SqlAlchemyUserReadRepository
from identity_app.modules.identity.infra.token_service import SERVICE_ROLE, TokenService

# `auto_error=False` so a missing header reaches our own handler and comes back
# in the contract's error envelope rather than FastAPI's `{"detail": ...}`.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_claims(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    tokens: TokenService = Depends(get_token_service),
) -> dict:
    """Verified JWT claims. Raises `401 TOKEN_MISSING` / `TOKEN_EXPIRED` /
    `TOKEN_INVALID` — the codes the contract tells consumers to expect."""
    if credentials is None or not credentials.credentials:
        raise ApiError(401, "TOKEN_MISSING", "Authentification requise.")
    claims = tokens.decode_access_token(credentials.credentials)
    request.state.claims = claims
    return claims


async def get_current_user_id(claims: dict = Depends(get_claims)) -> UUID:
    if claims.get("role") == SERVICE_ROLE:
        # A service token authenticates a machine, not a person; there is no
        # profile behind it, so routes like `/users/me` are meaningless.
        raise ApiError(403, "SERVICE_TOKEN_NOT_ALLOWED", "Cette route attend un utilisateur, pas un service.")
    status = claims.get("status")
    if status not in {s.value for s in SESSION_ALLOWED_STATUSES}:
        # A `pending_kyc` account passes: its owner must be able to open the app
        # and see where their request stands. Acting on anything is a separate
        # question, decided by each module from the same `status` claim.
        if status == UserStatus.SUSPENDED.value:
            raise ApiError(403, "USER_SUSPENDED", "Ce compte est suspendu.")
        raise ApiError(403, "USER_NOT_VERIFIED", "Ce compte n'a pas terminé sa vérification.")
    try:
        return UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise ApiError(401, "TOKEN_INVALID", "Claim `sub` absent ou malformé.") from exc


async def require_admin(
    user_id: UUID = Depends(get_current_user_id),
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
) -> User:
    """Admin gate, re-checked against the database.

    The extra read is affordable — back-office traffic is a rounding error next
    to the auth flows — and it closes the window where a revoked admin still
    holds a token that says otherwise.
    """
    user = await users.get_by_id(user_id)
    if user is None:
        raise ApiError(401, "TOKEN_INVALID", "Utilisateur introuvable.")
    # Admin routes demand a fully active account — no `pending_kyc` leniency
    # here, unlike reading one's own profile.
    if user.status != UserStatus.ACTIVE:
        raise ApiError(403, "USER_SUSPENDED", "Ce compte n'est pas actif.")
    if user.role != UserRole.ADMIN:
        raise ApiError(403, "FORBIDDEN_ROLE", "Rôle insuffisant pour cette action.")
    return user


async def require_service_or_admin(
    request: Request,
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    tokens: TokenService = Depends(get_token_service),
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
) -> UUID | None:
    """Caller is a backend service, or a human admin.

    Guards the two routes a module calls on its own behalf: `GET /users/{id}`
    and `PATCH /users/{id}/role`. Contract §5 leaves the mechanism open pending
    the Infra network decision, so both accepted forms are implemented and
    either can be switched off by configuration:

      * `X-Service-Key`, matched against `SERVICE_API_KEYS`;
      * an access token carrying `role=service`, minted by
        `scripts/issue_service_token.py`.

    Returns the acting admin's id, or `None` when the caller is a service —
    which is what lands in the audit trail's `changed_by`.
    """
    if x_service_key is not None:
        keys = settings.service_api_key_set
        if keys and x_service_key in keys:
            return None
        raise ApiError(401, "SERVICE_KEY_INVALID", "Clé de service inconnue.")

    if credentials is None or not credentials.credentials:
        raise ApiError(401, "TOKEN_MISSING", "Authentification requise.")

    claims = tokens.decode_access_token(credentials.credentials)
    request.state.claims = claims

    if claims.get("role") == SERVICE_ROLE:
        return None

    try:
        user_id = UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise ApiError(401, "TOKEN_INVALID", "Claim `sub` absent ou malformé.") from exc

    user = await users.get_by_id(user_id)
    if user is None:
        raise ApiError(401, "TOKEN_INVALID", "Utilisateur introuvable.")
    if user.status != UserStatus.ACTIVE:
        raise ApiError(403, "USER_SUSPENDED", "Ce compte n'est pas actif.")
    if user.role != UserRole.ADMIN:
        raise ApiError(
            403,
            "FORBIDDEN_ROLE",
            "Cette route est réservée aux appels service-à-service et aux administrateurs.",
        )
    return user.id
