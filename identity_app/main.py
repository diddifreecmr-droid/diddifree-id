"""ASGI entry point.

Routers are mounted under `settings.api_prefix` — `/identity/v1` by default,
matching the base URL the contract publishes. A gateway that already strips the
`/identity` segment sets `API_PREFIX=/v1` instead; no code changes.

JWKS is mounted twice on purpose (see `jwks_router`): once at the domain root
where `.well-known` belongs, once under the prefix where the contract documents
it. Consumers can use either and get the same key set.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from identity_app.core.errors import ApiError, api_error_handler, api_error_response
from identity_app.core.lifespan import lifespan
from identity_app.core.settings import settings
from identity_app.modules.identity.presentation.admin_router import router as admin_router
from identity_app.modules.identity.presentation.auth_router import router as auth_router
from identity_app.modules.identity.presentation.jwks_router import router as jwks_router
from identity_app.modules.identity.presentation.users_router import router as users_router

app = FastAPI(
    title=settings.app_name,
    description="Service d'identité central de l'écosystème DiddiFree.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origin_list,
    allow_origin_regex=settings.cors_allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Service-Key"],
)

app.add_exception_handler(ApiError, api_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    """Re-shape FastAPI's `{"detail": [...]}` into the ecosystem's envelope.

    Without this, a malformed body would answer in a format no consumer parses,
    and the contract's promise that *every* error looks the same would hold
    everywhere except the one place clients hit most while integrating.
    """
    return api_error_response(
        422,
        "VALIDATION_ERROR",
        "Certains champs de la requête sont invalides.",
        [
            {"field": ".".join(str(part) for part in error["loc"][1:]), "reason": error["msg"]}
            for error in exc.errors()
        ],
    )


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(users_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(jwks_router, prefix=settings.api_prefix)
app.include_router(jwks_router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
