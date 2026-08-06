"""Token issuance and verification — RS256 access tokens, opaque refresh tokens.

Access token claims are exactly what the contract publishes (§2):
`sub`, `role`, `status`, `iat`, `exp`, plus `iss` and the `kid` header used for
key selection. Nothing else. In particular no `full_name`: a profile edit must
not require re-issuing every live token, which is the reason `GET /users/me`
exists at all.

Refresh tokens are NOT JWTs. They are 256 bits of `secrets` randomness, stored
as a SHA-256 digest, which is what makes `POST /auth/logout` and account
suspension take effect immediately instead of at the next expiry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

import jwt

from identity_app.core.errors import ApiError
from identity_app.core.keys import KeyRing, get_key_ring
from identity_app.core.settings import settings

ALGORITHM = "RS256"

#: Role claim carried by service-to-service tokens. Not a `UserRole` — no row
#: in `identity.users` corresponds to it.
SERVICE_ROLE = "service"


def hash_refresh_token(raw_token: str) -> str:
    """Plain SHA-256, no salt and no pepper — deliberately.

    Unlike an OTP or a password, a refresh token already carries 256 bits of
    entropy, so there is no dictionary to run against the digest. What matters
    here is that the lookup is by exact hash, which a random salt would make
    impossible without scanning the table.
    """
    return sha256(raw_token.encode()).hexdigest()


class TokenService:
    def __init__(self, key_ring: KeyRing | None = None) -> None:
        self._key_ring = key_ring or get_key_ring()

    @property
    def published_kids(self) -> tuple[str, ...]:
        """Key ids currently served by JWKS — one normally, two mid-rotation."""
        return tuple(entry.kid for entry in self._key_ring.public_keys)

    # --- access tokens -----------------------------------------------------

    def issue_access_token(
        self,
        *,
        user_id: UUID,
        role: str,
        status: str,
        lifetime_minutes: int | None = None,
    ) -> str:
        now = datetime.now(UTC)
        lifetime = lifetime_minutes or settings.jwt_access_lifetime_minutes
        payload = {
            "sub": str(user_id),
            "role": role,
            "status": status,
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(minutes=lifetime),
        }
        return jwt.encode(
            payload,
            self._key_ring.private_pem,
            algorithm=ALGORITHM,
            # Consumers select the verification key by `kid`; omitting it would
            # make key rotation unimplementable on their side.
            headers={"kid": self._key_ring.active_kid},
        )

    def decode_access_token(self, token: str) -> dict:
        """Verify a token against the published keys.

        DiddiFreeID verifies its own tokens the same way every module does —
        against the JWKS key set, by `kid`. Any divergence between this path and
        a consumer's would show up as "works here, fails there", the hardest
        class of bug to diagnose across twelve teams.
        """
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise ApiError(401, "TOKEN_INVALID", f"Token invalide : {exc}") from exc

        kid = header.get("kid")
        entry = next((e for e in self._key_ring.public_keys if e.kid == kid), None)
        if entry is None:
            raise ApiError(401, "TOKEN_INVALID", "Token signé avec une clé inconnue (kid).")

        try:
            return jwt.decode(
                token,
                entry.pem,
                algorithms=[ALGORITHM],
                issuer=settings.jwt_issuer,
                options={"require": ["exp", "iat", "sub", "role"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ApiError(401, "TOKEN_EXPIRED", "Le token a expiré.") from exc
        except jwt.InvalidTokenError as exc:
            raise ApiError(401, "TOKEN_INVALID", f"Token invalide : {exc}") from exc

    # --- refresh tokens ----------------------------------------------------

    @staticmethod
    def new_refresh_token() -> tuple[str, str]:
        """Return `(raw_token, token_hash)`. The raw value is handed to the
        client and immediately forgotten server-side."""
        raw = f"opaque_{token_urlsafe(32)}"
        return raw, hash_refresh_token(raw)

    @staticmethod
    def refresh_expiry(now: datetime | None = None) -> datetime:
        return (now or datetime.now(UTC)) + timedelta(days=settings.refresh_token_lifetime_days)

    # --- JWKS --------------------------------------------------------------

    def jwks(self) -> dict:
        return self._key_ring.jwks()
