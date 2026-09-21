"""ASGI entry point.

Routers are mounted under `settings.api_prefix` — `/identity/v1` by default,
matching the base URL the contract publishes. A gateway that already strips the
`/identity` segment sets `API_PREFIX=/v1` instead; no code changes.

JWKS is mounted twice on purpose (see `jwks_router`): once at the domain root
where `.well-known` belongs, once under the prefix where the contract documents
it. Consumers can use either and get the same key set.
"""

import logging
import time

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from identity_app.core.errors import ApiError, api_error_handler, api_error_response
from identity_app.core.health import readiness_report
from identity_app.core.lifespan import lifespan
from identity_app.core.logging import configure_logging, new_request_id, reset_request_id, set_request_id
from identity_app.core.metrics import metrics_payload, observe_http_request, route_template
from identity_app.core.settings import settings
from identity_app.modules.identity.presentation.admin_router import router as admin_router
from identity_app.modules.identity.presentation.auth_router import router as auth_router
from identity_app.modules.identity.presentation.jwks_router import router as jwks_router
from identity_app.modules.identity.presentation.pro_router import router as pro_router
from identity_app.modules.identity.presentation.users_router import router as users_router

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

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
    allow_headers=["Authorization", "Content-Type", "X-Client-ID", "X-Service-Key"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Correlate every HTTP request without logging request bodies or secrets."""

    request_id = new_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    token = set_request_id(request_id)
    started_at = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        observe_http_request(
            method=request.method,
            route=route_template(request.scope),
            status_code=500,
            duration_seconds=time.perf_counter() - started_at,
        )
        logger.exception(
            "http_request_failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
            },
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        status_code = response.status_code
        observe_http_request(
            method=request.method,
            route=route_template(request.scope),
            status_code=status_code,
            duration_seconds=time.perf_counter() - started_at,
        )
        log_method = logger.info if status_code < 400 else logger.warning
        if status_code >= 500:
            log_method = logger.error
        log_method(
            "http_request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        reset_request_id(token)

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
app.include_router(pro_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(jwks_router, prefix=settings.api_prefix)
app.include_router(jwks_router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/live", tags=["ops"])
async def liveness() -> dict:
    """Process-level check that deliberately does not call dependencies."""

    return {"status": "ok", "app": settings.app_name}


@app.get("/health/ready", tags=["ops"])
async def readiness() -> JSONResponse:
    ready, checks = await readiness_report(app)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "app": settings.app_name,
            "checks": checks,
        },
    )


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)
