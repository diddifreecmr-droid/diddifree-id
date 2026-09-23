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
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    tokens: TokenService = Depends(get_token_service),
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
) -> UUID | None:
    """Caller is a backend service, or a human admin.

    Guards the two routes a module calls on its own behalf: `GET /users/{id}`
    and `PATCH /users/{id}/role`. New integrations use a short-lived
    client-credentials JWT plus `X-Client-ID`. `X-Service-Key` remains
    accepted only for legacy integrations during the migration window:

      * `X-Service-Key`, matched against `SERVICE_API_KEYS`;
      * a client-credentials token carrying `role=service`, minted by
        `POST /auth/service/token`.

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
        if claims.get("token_type") == "service":
            if not x_client_id or x_client_id != claims.get("client_id"):
                raise ApiError(
                    401,
                    "SERVICE_CLIENT_ID_INVALID",
                    "X-Client-ID ne correspond pas au client du token service.",
                )
            required_scope = _required_service_scope(request)
            if required_scope is None:
                raise ApiError(403, "SERVICE_SCOPE_INVALID", "Cette route n'a pas de scope service déclaré.")
            tokens.decode_service_token(
                credentials.credentials,
                audience=settings.jwt_issuer,
                required_scopes={required_scope},
            )
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


async def require_capability_service(
    request: Request,
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    tokens: TokenService = Depends(get_token_service),
) -> None:
    """Authorize a module updating its own operational projection.

    The service name in the JWT must match the path segment. This prevents a
    valid DiddiSend client from writing a DiddiGo projection by changing only
    the URL.
    """
    if credentials is None or not credentials.credentials:
        raise ApiError(401, "TOKEN_MISSING", "Authentification requise.")
    if not x_client_id:
        raise ApiError(401, "SERVICE_CLIENT_ID_INVALID", "X-Client-ID est requis.")

    claims = tokens.decode_access_token(credentials.credentials)
    if claims.get("role") != SERVICE_ROLE or claims.get("token_type") != "service":
        raise ApiError(401, "SERVICE_TOKEN_INVALID", "Token service invalide.")
    if claims.get("status") != UserStatus.ACTIVE.value:
        raise ApiError(401, "SERVICE_TOKEN_INVALID", "Token service inactif.")
    if x_client_id != claims.get("client_id"):
        raise ApiError(401, "SERVICE_CLIENT_ID_INVALID", "X-Client-ID ne correspond pas au client du token service.")
    target_service = request.path_params.get("service")
    if target_service != claims.get("service"):
        raise ApiError(403, "SERVICE_CAPABILITY_OWNER_INVALID", "Le service ne peut modifier que sa propre projection.")
    tokens.decode_service_token(
        credentials.credentials,
        audience=settings.jwt_issuer,
        required_scopes={"capabilities:write"},
    )


async def require_pilotage_reporting(
    request: Request,
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    tokens: TokenService = Depends(get_token_service),
) -> None:
    """Authorize Pilotage's aggregate identity-reporting read surface."""

    if credentials is None or not credentials.credentials:
        raise ApiError(401, "TOKEN_MISSING", "Authentification service requise.")
    if not x_client_id:
        raise ApiError(401, "SERVICE_CLIENT_ID_INVALID", "X-Client-ID est requis.")

    claims = tokens.decode_access_token(credentials.credentials)
    request.state.claims = claims
    if claims.get("role") != SERVICE_ROLE or claims.get("token_type") != "service":
        raise ApiError(401, "SERVICE_TOKEN_INVALID", "Token service invalide.")
    if claims.get("service") != "pilotage":
        raise ApiError(403, "SERVICE_REPORTING_FORBIDDEN", "Seul Pilotage peut lire ce résumé.")
    if x_client_id != claims.get("client_id"):
        raise ApiError(401, "SERVICE_CLIENT_ID_INVALID", "X-Client-ID ne correspond pas au token service.")
    tokens.decode_service_token(
        credentials.credentials,
        audience=settings.jwt_issuer,
        required_scopes={"identity:reporting:read"},
    )


async def require_backoffice_capability_read(
    request: Request,
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    tokens: TokenService = Depends(get_token_service),
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
) -> User | None:
    """Allow an admin or the dedicated Backoffice service to read one user's capabilities."""
    return await _require_admin_or_backoffice_capability(
        request=request,
        required_scope="capabilities:read",
        x_client_id=x_client_id,
        credentials=credentials,
        tokens=tokens,
        users=users,
    )


async def require_backoffice_capability_write(
    request: Request,
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    tokens: TokenService = Depends(get_token_service),
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
) -> User | None:
    """Allow an admin or Backoffice to change global capability access."""
    return await _require_admin_or_backoffice_capability(
        request=request,
        required_scope="capabilities:access:write",
        x_client_id=x_client_id,
        credentials=credentials,
        tokens=tokens,
        users=users,
    )


async def _require_admin_or_backoffice_capability(
    *,
    request: Request,
    required_scope: str,
    x_client_id: str | None,
    credentials: HTTPAuthorizationCredentials,
    tokens: TokenService,
    users: SqlAlchemyUserReadRepository,
) -> User | None:
    if credentials is None or not credentials.credentials:
        raise ApiError(401, "TOKEN_MISSING", "Authentification requise.")

    claims = tokens.decode_access_token(credentials.credentials)
    request.state.claims = claims
    if claims.get("role") == SERVICE_ROLE:
        if claims.get("service") != "backoffice":
            raise ApiError(403, "SERVICE_CAPABILITY_ACCESS_FORBIDDEN", "Seul le Backoffice peut gérer cet accès.")
        if not x_client_id or x_client_id != claims.get("client_id"):
            raise ApiError(
                401,
                "SERVICE_CLIENT_ID_INVALID",
                "X-Client-ID ne correspond pas au client du token service.",
            )
        tokens.decode_service_token(
            credentials.credentials,
            audience=settings.jwt_issuer,
            required_scopes={required_scope},
        )
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
        raise ApiError(403, "FORBIDDEN_ROLE", "Rôle insuffisant pour cette action.")
    return user


def _required_service_scope(request: Request) -> str | None:
    """Map existing service routes to the scoped-token contract.

    Legacy `role=service` tokens intentionally bypass this map during the
    migration window. New client-credentials tokens must be explicit.
    """
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    if request.method == "GET" and route_path.endswith("/users/backfill"):
        return "users:backfill:read"
    if request.method == "GET" and route_path.endswith("/users/{user_id}"):
        return "profile:read"
    if request.method == "PATCH" and route_path.endswith("/users/{user_id}/role"):
        return "role:write"
    return None
