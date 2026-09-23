"""Pydantic request/response models.

Request bodies are validated strictly; response bodies are documented as models
but the handlers return plain dicts built by the application layer, so the
published JSON stays in one place (the command or query) rather than being
reshaped a second time here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

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
    phone: str | None = Field(default=None, examples=["+2250700000000"])
    email: EmailAddress | None = Field(default=None, examples=["awa@example.com"])
    full_name: str | None = Field(default=None, max_length=120, examples=["Awa Koné"])

    @model_validator(mode="after")
    def require_identifier(self) -> RegisterRequest:
        if not self.phone and not self.email:
            raise ValueError("phone ou email requis")
        return self


class OtpRequestBody(BaseModel):
    phone: str | None = Field(default=None, examples=["+2250700000000"])
    email: EmailAddress | None = Field(default=None, examples=["awa@example.com"])
    channel: Literal["email", "telegram", "whatsapp"] | None = Field(
        default=None,
        description="Canal OTP. Si absent, OTP_PROVIDER est utilisé.",
    )

    @model_validator(mode="after")
    def require_one_identifier(self) -> OtpRequestBody:
        if bool(self.phone) == bool(self.email):
            raise ValueError("exactement un identifiant phone ou email requis")
        return self


class OtpVerifyRequest(BaseModel):
    phone: str | None = Field(default=None, examples=["+2250700000000"])
    email: EmailAddress | None = Field(default=None, examples=["awa@example.com"])
    # Exactly six digits. Enforced here so a malformed code is a `422` on the
    # field rather than a wasted attempt against the counter that protects the
    # real code.
    code: str = Field(pattern=r"^\d{6}$", examples=["482913"])
    device_info: str | None = Field(default=None, max_length=200, examples=["iPhone 13 · iOS 17.4"])

    @model_validator(mode="after")
    def require_one_identifier(self) -> OtpVerifyRequest:
        if bool(self.phone) == bool(self.email):
            raise ValueError("exactement un identifiant phone ou email requis")
        return self


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


class CapabilityProjectionRequest(BaseModel):
    operational_status: str = Field(min_length=1, max_length=80, examples=["vehicle_missing"])
    actions: list[str] = Field(default_factory=list, max_length=20, examples=[["complete_vehicle"]])
    projection_version: int = Field(ge=1, examples=[2])
    event_id: str | None = Field(default=None, max_length=160)


class CapabilityAccessRequest(BaseModel):
    access_status: Literal["requested", "enabled", "suspended", "revoked"]


class ServiceClientUpdateRequest(BaseModel):
    """Mutable machine-client policy; secrets are never accepted or returned."""

    allowed_audiences: list[str] | None = Field(default=None, min_length=1, max_length=20)
    allowed_scopes: list[str] | None = Field(default=None, min_length=1, max_length=50)
    active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> ServiceClientUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("au moins un champ doit être modifié")
        for field_name in ("allowed_audiences", "allowed_scopes"):
            values = getattr(self, field_name)
            if field_name in self.model_fields_set and values is None:
                raise ValueError(f"{field_name} ne peut pas être null")
            if values is not None:
                normalized = list(dict.fromkeys(value.strip() for value in values))
                if not normalized or any(not value or len(value) > 120 for value in normalized):
                    raise ValueError(f"{field_name} contient une valeur invalide")
                setattr(self, field_name, normalized)
        return self


class ServiceClientResponse(BaseModel):
    client_id: str
    service_name: str
    environment: str
    allowed_audiences: list[str]
    allowed_scopes: list[str]
    active: bool
    expires_at: str | None
    revoked_at: str | None


class ServiceClientListResponse(BaseModel):
    data: list[ServiceClientResponse]


# --- responses --------------------------------------------------------------

class UserProfile(BaseModel):
    id: str
    phone: str | None
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
    phone: str | None
    status: str


class OtpRequestResponse(BaseModel):
    expires_in_seconds: int
    retry_after_seconds: int
    channel: Literal["email", "telegram", "whatsapp", "logging"]


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str


class ServiceTokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    scope: str


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


class CapabilityResponse(BaseModel):
    service: str
    type: str
    access_status: Literal["requested", "enabled", "suspended", "revoked"]
    operational_status: str
    status_source: str
    actions: list[str]
    projection_version: int
    last_event_id: str | None
    updated_at: str
    created_at: str
    freshness: Literal["fresh", "stale"] = "fresh"


class ProMeResponse(BaseModel):
    user_id: str
    calculated_at: str
    capabilities: list[CapabilityResponse]


class IdentityMetricResponse(BaseModel):
    name: str
    value: int
    unit: str


class IdentitySummarySourceResponse(BaseModel):
    module: str
    record_type: str


class IdentitySummaryResponse(BaseModel):
    contract_version: str
    module: str
    date: str
    timezone: str
    is_final: bool
    metrics: list[IdentityMetricResponse]
    calculated_at: str
    sources: list[IdentitySummarySourceResponse]
