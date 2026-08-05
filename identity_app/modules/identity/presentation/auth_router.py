"""`/auth/*` — contract §1, token issuance and lifecycle.

These are the only routes a frontend calls on DiddiFreeID directly. Everything
a *module* needs happens either locally against the JWKS, or through the routes
in `users_router` / `admin_router`.
"""

from fastapi import APIRouter, Depends, Request, Response

from identity_app.core.deps import (
    logout_command,
    refresh_token_command,
    register_user_command,
    request_otp_command,
    verify_otp_command,
)
from identity_app.modules.identity.application.commands import (
    Logout,
    RefreshAccessToken,
    RegisterUser,
    RequestOtp,
    VerifyOtp,
)
from identity_app.modules.identity.presentation.schemas import (
    AuthenticatedResponse,
    LogoutRequest,
    OtpRequestBody,
    OtpRequestResponse,
    OtpVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenPairResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201, response_model=RegisterResponse)
async def register(
    payload: RegisterRequest,
    command: RegisterUser = Depends(register_user_command),
) -> dict:
    return await command(
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        full_name=payload.full_name,
    )


@router.post("/otp/request", response_model=OtpRequestResponse)
async def request_otp(
    payload: OtpRequestBody,
    request: Request,
    command: RequestOtp = Depends(request_otp_command),
) -> dict:
    return await command(
        phone=payload.phone,
        channel=payload.channel,
        client_ip=_client_ip(request),
    )


@router.post("/otp/verify", response_model=AuthenticatedResponse)
async def verify_otp(
    payload: OtpVerifyRequest,
    command: VerifyOtp = Depends(verify_otp_command),
) -> dict:
    return await command(phone=payload.phone, code=payload.code, device_info=payload.device_info)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(
    payload: RefreshRequest,
    command: RefreshAccessToken = Depends(refresh_token_command),
) -> dict:
    return await command(refresh_token=payload.refresh_token, device_info=payload.device_info)


@router.post("/logout", status_code=204)
async def logout(
    payload: LogoutRequest,
    command: Logout = Depends(logout_command),
) -> Response:
    await command(refresh_token=payload.refresh_token, all_devices=payload.all_devices)
    # The contract promises 204 with no content; FastAPI would otherwise
    # serialise a `null` body, which some HTTP clients reject on a 204.
    return Response(status_code=204)


def _client_ip(request: Request) -> str | None:
    """Best-effort caller IP for the per-IP OTP limit.

    `X-Forwarded-For` is trusted only because this service is expected to sit
    behind the ecosystem's own gateway, which sets it. Exposed directly to the
    internet the header is caller-controlled and the per-IP limit becomes
    decorative — the per-phone limit, which no header can influence, is the one
    that still holds in that case.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
