"""Pydantic request/response models.

Request bodies are validated strictly; response bodies are documented as models
but the handlers return plain dicts built by the application layer, so the
published JSON stays in one place (the command or query) rather than being
reshaped a second time here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]


class RegisterRequest(BaseModel):
    phone: str = Field(examples=["+2250700000000"])
    email: EmailAddress | None = Field(default=None, examples=["awa@example.com"])
    full_name: str | None = Field(default=None, max_length=120, examples=["Awa Koné"])


class OtpRequestBody(BaseModel):
    phone: str = Field(examples=["+2250700000000"])
    channel: Literal["email", "telegram"] | None = Field(
        default=None,
        description="Canal OTP. Si absent, OTP_PROVIDER est utilisé.",
    )


class OtpVerifyRequest(BaseModel):
    phone: str = Field(examples=["+2250700000000"])
    # Exactly six digits. Enforced here so a malformed code is a `422` on the
    # field rather than a wasted attempt against the counter that protects the
    # real code.
    code: str = Field(pattern=r"^\d{6}$", examples=["482913"])
    device_info: str | None = Field(default=None, max_length=200, examples=["iPhone 13 · iOS 17.4"])


class RefreshRequest(BaseModel):
    refresh_token: str
    device_info: str | None = Field(default=None, max_length=200)


class LogoutRequest(BaseModel):
    refresh_token: str
    all_devices: bool = False


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    email: EmailAddress | None = None
    language: Literal["fr", "en"] | None = None
    photo_url: str | None = Field(default=None, max_length=2048)


class ChangeRoleRequest(BaseModel):
    role: str = Field(examples=["admin"])
    reason: str | None = Field(
        default=None,
        examples=["Validation KYC chauffeur DiddiGo, dossier #4021"],
    )


class ChangeStatusRequest(BaseModel):
    status: str = Field(examples=["suspended"])
    reason: str | None = Field(default=None, examples=["Signalement fraude, ticket #883"])


class KycDecisionRequest(BaseModel):
    """Resolution of a pending role request.

    A boolean rather than a free-form status: there are exactly two outcomes,
    and an enum of two values invites a third that nothing downstream handles.
    """

    approved: bool = Field(examples=[True])
    reason: str | None = Field(
        default=None,
        examples=["Permis vérifié, pièce d'identité conforme — dossier #4021"],
    )


# --- responses --------------------------------------------------------------

class UserProfile(BaseModel):
    id: str
    phone: str
    email: EmailAddress | None
    full_name: str | None
    language: Literal["fr", "en"]
    photo_url: str | None
    role: str
    status: str
    #: Role awaiting a KYC decision, `null` when nothing is pending. Additive to
    #: the shape published in contract §2.
    requested_role: str | None = None


class RegisterResponse(BaseModel):
    user_id: str
    phone: str
    status: str


class OtpRequestResponse(BaseModel):
    expires_in_seconds: int
    retry_after_seconds: int


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str


class AuthenticatedResponse(TokenPairResponse):
    user: UserProfile


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class UserListResponse(BaseModel):
    data: list[UserProfile]
    pagination: Pagination
