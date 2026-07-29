"""Error envelope — byte-for-byte the shape DiddiGo already returns.

    {"error": {"code": "USER_NOT_FOUND", "message": "...", "details": null}}

Keeping one envelope across the ecosystem is the whole reason the contract
document repeats DiddiGo's conventions instead of inventing new ones.
"""

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


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


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return api_error_response(exc.status_code, exc.code, exc.message, exc.details)
