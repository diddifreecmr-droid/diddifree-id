"""Provider-neutral OTP delivery contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OtpDeliveryRequest:
    """The information an OTP transport needs, without provider details."""

    phone: str | None
    email: str | None
    code: str
    channel: str
    expires_in_seconds: int
    idempotency_key: str | None = None


@dataclass(frozen=True)
class OtpDeliveryResult:
    """A normalized provider result for logs, metrics, and future retries."""

    channel: str
    provider: str
    status: str = "accepted"
    provider_message_id: str | None = None


class OtpDeliveryAdapter(Protocol):
    async def deliver(self, request: OtpDeliveryRequest) -> OtpDeliveryResult:
        """Deliver one OTP through one configured provider."""
        ...
