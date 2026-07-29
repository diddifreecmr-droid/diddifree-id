"""FastAPI dependencies — the single place where abstractions meet concretions.

Routers never construct a repository or a command themselves; they declare what
they need and this module wires it. That indirection is what makes the ports in
`domain/interfaces.py` more than decoration: swapping an implementation is an
edit here, not a sweep through the routers.

Note the shape of the wiring: a command factory only ever receives write
repositories, a query factory only read ones. The CQRS rule is enforced by
what is available, not by remembering to follow it.
"""

# NOTE: deliberately no `from __future__ import annotations`. FastAPI reads the
# runtime annotations of dependency functions; under PEP 563 the `Request`
# parameters below arrive as the string "Request", which FastAPI cannot
# recognise as the ASGI request and instead treats as a required query
# parameter — producing `422 missing query.request` on every dependent route.

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from identity_app.core.database import get_session
from identity_app.core.redis import get_redis  # noqa: F401 — re-exported
from identity_app.modules.identity.application.commands import (
    ChangeRole,
    ChangeStatus,
    DecideKyc,
    Logout,
    RefreshAccessToken,
    RegisterUser,
    RequestOtp,
    UpdateProfile,
    VerifyOtp,
)
from identity_app.modules.identity.application.queries import (
    GetCurrentUserProfile,
    GetJwks,
    GetUserById,
    ListUsers,
)
from identity_app.modules.identity.infra.cache import RedisProfileCache
from identity_app.modules.identity.infra.rate_limiter import RedisOtpRateLimiter
from identity_app.modules.identity.infra.read_repository import SqlAlchemyUserReadRepository
from identity_app.modules.identity.infra.sms_adapter import LoggingOtpSender
from identity_app.modules.identity.infra.token_service import TokenService
from identity_app.modules.identity.infra.write_repository import (
    SqlAlchemyOtpRepository,
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyUserWriteRepository,
)
from identity_app.shared_kernel.events.bus import RedisEventPublisher

# --- sessions & shared resources -------------------------------------------

# `get_session` is already an async-generator dependency that commits on success
# and rolls back on error. Re-export it directly rather than wrapping it: an
# `async for` wrapper is abandoned mid-iteration when FastAPI closes the outer
# dependency, so the inner generator's code after `yield` — the commit — never
# runs, and every write is silently lost.
session_dep = get_session


def get_token_service(request: Request) -> TokenService:
    """The token service holds the loaded key ring, so it is built once by the
    lifespan rather than per request — parsing two PEM files on every call to
    `/auth/refresh` would be pure waste."""
    service = getattr(request.app.state, "tokens", None)
    if service is None:
        service = TokenService()
        request.app.state.tokens = service
    return service


# --- write repositories (commands only) ------------------------------------

async def user_write_repo(session: AsyncSession = Depends(session_dep)) -> SqlAlchemyUserWriteRepository:
    return SqlAlchemyUserWriteRepository(session)


async def otp_repo(session: AsyncSession = Depends(session_dep)) -> SqlAlchemyOtpRepository:
    return SqlAlchemyOtpRepository(session)


async def refresh_token_repo(
    session: AsyncSession = Depends(session_dep),
) -> SqlAlchemyRefreshTokenRepository:
    return SqlAlchemyRefreshTokenRepository(session)


# --- read repositories (queries only) --------------------------------------

async def user_read_repo(session: AsyncSession = Depends(session_dep)) -> SqlAlchemyUserReadRepository:
    return SqlAlchemyUserReadRepository(session)


# --- infrastructure services -----------------------------------------------

def profile_cache(redis: Redis = Depends(get_redis)) -> RedisProfileCache:
    return RedisProfileCache(redis)


def event_publisher(redis: Redis = Depends(get_redis)) -> RedisEventPublisher:
    return RedisEventPublisher(redis)


def otp_rate_limiter(redis: Redis = Depends(get_redis)) -> RedisOtpRateLimiter:
    return RedisOtpRateLimiter(redis)


def otp_sender() -> LoggingOtpSender:
    return LoggingOtpSender()


# --- commands ---------------------------------------------------------------

def register_user_command(
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
) -> RegisterUser:
    return RegisterUser(users=users)


def request_otp_command(
    otps: SqlAlchemyOtpRepository = Depends(otp_repo),
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
    sender: LoggingOtpSender = Depends(otp_sender),
    limiter: RedisOtpRateLimiter = Depends(otp_rate_limiter),
) -> RequestOtp:
    return RequestOtp(otps=otps, users=users, sender=sender, rate_limiter=limiter)


def verify_otp_command(
    otps: SqlAlchemyOtpRepository = Depends(otp_repo),
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
    refresh_tokens: SqlAlchemyRefreshTokenRepository = Depends(refresh_token_repo),
    tokens: TokenService = Depends(get_token_service),
    events: RedisEventPublisher = Depends(event_publisher),
    cache: RedisProfileCache = Depends(profile_cache),
) -> VerifyOtp:
    return VerifyOtp(
        otps=otps,
        users=users,
        refresh_tokens=refresh_tokens,
        tokens=tokens,
        events=events,
        cache=cache,
    )


def refresh_token_command(
    refresh_tokens: SqlAlchemyRefreshTokenRepository = Depends(refresh_token_repo),
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
    tokens: TokenService = Depends(get_token_service),
) -> RefreshAccessToken:
    return RefreshAccessToken(refresh_tokens=refresh_tokens, users=users, tokens=tokens)


def logout_command(
    refresh_tokens: SqlAlchemyRefreshTokenRepository = Depends(refresh_token_repo),
) -> Logout:
    return Logout(refresh_tokens=refresh_tokens)


def update_profile_command(
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
    events: RedisEventPublisher = Depends(event_publisher),
    cache: RedisProfileCache = Depends(profile_cache),
) -> UpdateProfile:
    return UpdateProfile(users=users, events=events, cache=cache)


def change_role_command(
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
    events: RedisEventPublisher = Depends(event_publisher),
    cache: RedisProfileCache = Depends(profile_cache),
) -> ChangeRole:
    return ChangeRole(users=users, events=events, cache=cache)


def decide_kyc_command(
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
    events: RedisEventPublisher = Depends(event_publisher),
    cache: RedisProfileCache = Depends(profile_cache),
) -> DecideKyc:
    return DecideKyc(users=users, events=events, cache=cache)


def change_status_command(
    users: SqlAlchemyUserWriteRepository = Depends(user_write_repo),
    refresh_tokens: SqlAlchemyRefreshTokenRepository = Depends(refresh_token_repo),
    events: RedisEventPublisher = Depends(event_publisher),
    cache: RedisProfileCache = Depends(profile_cache),
) -> ChangeStatus:
    return ChangeStatus(users=users, refresh_tokens=refresh_tokens, events=events, cache=cache)


# --- queries ----------------------------------------------------------------

def get_user_by_id_query(
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
    cache: RedisProfileCache = Depends(profile_cache),
) -> GetUserById:
    return GetUserById(users=users, cache=cache)


def get_current_profile_query(
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
    cache: RedisProfileCache = Depends(profile_cache),
) -> GetCurrentUserProfile:
    return GetCurrentUserProfile(users=users, cache=cache)


def list_users_query(
    users: SqlAlchemyUserReadRepository = Depends(user_read_repo),
) -> ListUsers:
    return ListUsers(users=users)


def get_jwks_query(tokens: TokenService = Depends(get_token_service)) -> GetJwks:
    return GetJwks(tokens=tokens)
