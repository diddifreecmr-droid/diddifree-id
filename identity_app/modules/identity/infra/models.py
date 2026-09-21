"""SQLAlchemy models — the `identity` schema from architecture §4, verbatim.

Both repositories map to these same tables. That is precisely the "CQRS léger"
decision: the separation is a discipline in the code, not two databases to keep
in sync. If read volume ever forces a real split, only `read_repository.py`
changes — the models, and every command above them, stay as they are.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from identity_app.core.database import Base


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_phone", "phone"),
        Index("idx_users_email", "email", unique=True),
        # Supports the `?role=driver` filter of `GET /admin/users`.
        Index("idx_users_role", "role"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str] = mapped_column(String(2), nullable=False, server_default=text("'fr'"))
    photo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'user'"))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending_verification'"),
    )
    # Role awaiting a KYC decision. NULL means nothing is pending — which is
    # also what makes `WHERE requested_role IS NOT NULL` the review queue.
    requested_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} phone={self.phone!r} role={self.role} status={self.status}>"


class OtpCodeModel(Base):
    __tablename__ = "otp_codes"
    __table_args__ = (
        Index("idx_otp_phone", "phone"),
        Index("idx_otp_email", "email"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("idx_refresh_user", "user_id"),
        # Every refresh and logout looks a token up by hash and nothing else.
        Index("idx_refresh_token_hash", "token_hash"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The token itself is never stored — only its hash, so a database dump
    # cannot be replayed as a set of live sessions (architecture §4).
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    device_info: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class UserRoleHistoryModel(Base):
    """Audit of role decisions. `to_role IS NULL` marks a refused KYC."""

    __tablename__ = "user_role_history"
    __table_args__ = (
        Index("idx_role_history_user", "user_id"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requested_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class UserStatusHistoryModel(Base):
    __tablename__ = "user_status_history"
    __table_args__ = {"schema": "identity"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class ServiceClientModel(Base):
    """Machine credentials; the plaintext secret is never persisted."""

    __tablename__ = "service_clients"
    __table_args__ = (
        Index("uq_service_clients_client_id", "client_id", unique=True),
        Index("idx_service_clients_service_environment", "service_name", "environment"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    client_id: Mapped[str] = mapped_column(String(120), nullable=False)
    service_name: Mapped[str] = mapped_column(String(80), nullable=False)
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed_audiences: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list,
    )
    allowed_scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )


class UserCapabilityModel(Base):
    """Global capability projection used by DiddiFree Pro.

    Business modules remain the source of operational truth. This row only
    stores the coarse access decision and the latest module projection.
    """

    __tablename__ = "user_capabilities"
    __table_args__ = (
        Index("uq_user_capabilities_user_service_type", "user_id", "service", "capability_type", unique=True),
        Index("idx_user_capabilities_user", "user_id"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    service: Mapped[str] = mapped_column(String(80), nullable=False)
    capability_type: Mapped[str] = mapped_column(String(80), nullable=False)
    access_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'requested'"),
    )
    operational_status: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default=text("'unknown'"),
    )
    status_source: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default=text("'diddifreeid'"),
    )
    actions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list,
    )
    projection_version: Mapped[int] = mapped_column(
        nullable=False, server_default=text("1"), default=1,
    )
    last_event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
