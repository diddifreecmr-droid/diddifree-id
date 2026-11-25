"""Error envelope — byte-for-byte the shape DiddiGo already returns.

    {"error": {"code": "USER_NOT_FOUND", "message": "...", "details": null}}

Keeping one envelope across the ecosystem is the whole reason the contract
document repeats DiddiGo's conventions instead of inventing new ones.
"""

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from identity_app.core.metrics import route_template

logger = logging.getLogger(__name__)


@dataclass
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: Any | None = None


def api_error_response(status_code: int, code: str, message: str, details: Any | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    # The request-completion event only carries the status. The contract code
    # is what tells an operator *which* 401 is flooding the logs. `details`
    # stays out: it can echo caller-supplied field values.
    log = logger.error if exc.status_code >= 500 else logger.warning
    log(
        "Erreur API %s",
        exc.code,
        extra={
            "event": "api.error",
            "error_code": exc.code,
            "method": request.method,
            "route": route_template(request.scope),
            "status_code": exc.status_code,
        },
    )
    return api_error_response(exc.status_code, exc.code, exc.message, exc.details)
