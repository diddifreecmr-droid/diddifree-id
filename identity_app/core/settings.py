"""Application settings, powered by pydantic-settings.

Sources (highest priority first):
  1. process environment (useful in tests / docker-compose)
  2. values from `./.env` (local dev — never committed)
  3. defaults declared below

Instantiated at module import time as `settings` — importers do
`from identity_app.core.settings import settings`.
"""

from __future__ import annotations

import json
import re
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "DiddiFreeID"
    environment: str = "development"
    log_level: str = "INFO"
    health_check_timeout_seconds: float = 2.0
    # The API contract states the base URL as `.../identity/v1`, so the prefix
    # carries the module segment too. A gateway that already strips `/identity`
    # can set API_PREFIX=/v1 without a code change.
    api_prefix: str = "/identity/v1"
    # Comma-separated browser origins. Empty keeps CORS disabled by default.
    cors_allowed_origins: str = ""
    # Local development/staging frontends may use any localhost port.
    cors_allowed_origin_regex: str | None = r"^https?://(localhost|127[.]0[.]0[.]1)(:[0-9]+)?$"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5435/diddi_free_id"
    redis_url: str = "redis://localhost:6381/0"

    # --- RS256 signing material (architecture §5) --------------------------
    # Paths, not inline PEM: the private key arrives as a mounted file from the
    # secrets vault, and a path in the environment cannot leak the key itself
    # into a process listing or a crash dump.
    jwt_private_key_path: str = "keys/private.pem"
    jwt_public_key_path: str = "keys/public.pem"
    jwt_active_kid: str = "dev-2026-07-01"
    # Second key, published alongside the active one during a rotation so
    # tokens signed before the switch keep verifying until they expire.
    jwt_previous_public_key_path: str | None = None
    jwt_previous_kid: str | None = None

    jwt_issuer: str = "diddifree-id"
    jwt_access_lifetime_minutes: int = 15
    refresh_token_lifetime_days: int = 30
    service_token_lifetime_seconds: int = 600
    account_deletion_grace_days: int = 30

    # --- OTP ---------------------------------------------------------------
    otp_code_lifetime_seconds: int = 300
    otp_rate_limit_seconds: int = 60
    otp_max_attempts: int = 5
    otp_hash_pepper: str = "change-me-in-prod-32-characters-minimum"
    otp_log_plaintext: bool = True
    # Google Play reviewers keep the normal six-digit-code UI, but their code
    # is provisioned out-of-band rather than delivered by an OTP provider.
    # The map is deliberately a JSON string so it can be set as one Portainer
    # secret: {"<user_uuid>": "123456"}. Never commit its real value.
    review_static_otp_enabled: bool = False
    review_static_otp_codes_json: str = ""
    review_static_otp_max_attempts: int = 5
    review_static_otp_lock_seconds: int = 900

    # The request body may override this with `sms`, `email`, `telegram` or `whatsapp`.
    otp_provider: str = "logging"
    # The frontend selects a channel; the backend selects its provider.
    otp_sms_provider: str = "logging"
    evolution_api_url: str | None = None
    evolution_api_key: str | None = None
    evolution_instance: str | None = None
    evolution_api_timeout_seconds: int = 20
    telegram_bot_token: str | None = None
    telegram_poll_timeout_seconds: int = 25
    # The provider-specific SMTP host must be supplied by Portainer/.env.
    # Keeping it empty avoids silently routing production mail through Gmail.
    smtp_host: str = "smtp.zoho.com"
    smtp_port: int = 587
    smtp_username: str | None = "direction.technique@diddifree.com"
    smtp_password: str | None = None
    smtp_from_email: str = "no-reply@diddifree.com"
    smtp_from_name: str = "DiddiFreeID"
    smtp_use_tls: bool = True
    yellika_sms_base_url: str = "https://panel.yellikasms.com"
    yellika_sms_token: str | None = None
    yellika_sms_sender_id: str | None = None
    yellika_sms_timeout_seconds: int = 20
    senndo_sms_base_url: str = "https://api.senndo.com"
    senndo_sms_api_key: str | None = None
    senndo_sms_timeout_seconds: int = 30

    # --- Service-to-service (JWT standard; X-Service-Key is legacy) ----------
    service_api_keys: str = ""
    capability_projection_stale_seconds: int = 300
    identity_reporting_timezone: str = "Africa/Abidjan"

    @property
    def service_api_key_set(self) -> frozenset[str]:
        """Parsed `SERVICE_API_KEYS`. Empty means key-based service auth is
        disabled and only `role=service` access tokens are accepted."""
        return frozenset(key.strip() for key in self.service_api_keys.split(",") if key.strip())

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        """Return configured browser origins without empty entries."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def review_static_otp_codes(self) -> dict[str, str]:
        """Return the reviewed, per-user static-code map from configuration.

        Parsing is intentionally strict. A malformed review configuration must
        stop the identity service rather than quietly creating a bypass or
        falling back to an unexpected delivery provider.
        """
        if not self.review_static_otp_enabled:
            return {}
        try:
            raw_codes = json.loads(self.review_static_otp_codes_json)
        except json.JSONDecodeError as exc:
            raise ValueError("REVIEW_STATIC_OTP_CODES_JSON doit être un objet JSON valide.") from exc
        if not isinstance(raw_codes, dict) or not raw_codes:
            raise ValueError("REVIEW_STATIC_OTP_CODES_JSON doit contenir au moins un code par user_id.")
        if self.review_static_otp_max_attempts < 1:
            raise ValueError("REVIEW_STATIC_OTP_MAX_ATTEMPTS doit être supérieur à zéro.")
        if self.review_static_otp_lock_seconds < 1:
            raise ValueError("REVIEW_STATIC_OTP_LOCK_SECONDS doit être supérieur à zéro.")

        codes: dict[str, str] = {}
        for raw_user_id, code in raw_codes.items():
            if not isinstance(raw_user_id, str) or not isinstance(code, str):
                raise ValueError("Chaque code Review doit être indexé par un user_id UUID et être une chaîne.")
            try:
                user_id = str(UUID(raw_user_id))
            except ValueError as exc:
                raise ValueError("REVIEW_STATIC_OTP_CODES_JSON contient un user_id invalide.") from exc
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError("Chaque code Review doit contenir exactement six chiffres.")
            codes[user_id] = code
        return codes


settings = Settings()
