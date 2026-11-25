"""Verified contact-link challenges for existing user accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class ContactLinkChallenge:
    id: UUID
    user_id: UUID
    contact_type: str
    target: str
    code_hash: str
    expires_at: datetime
    created_at: datetime
    consumed_at: datetime | None = None
    attempts: int = 0

    @staticmethod
    def new_id() -> UUID:
        return uuid4()

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now
