"""initial identity schema

Creates the `identity` schema of architecture §4: users, otp_codes,
refresh_tokens and the user_status_history audit table.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Both are idempotent, and both are needed when migrating against a
    # database that docker/postgres-init.sql never touched — a managed Postgres
    # instance in staging, or an existing cluster shared with DiddiGo.
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=20), server_default=sa.text("'user'"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pending_verification'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone"),
        schema="identity",
    )
    op.create_index("idx_users_phone", "users", ["phone"], schema="identity")
    op.create_index("idx_users_role", "users", ["role"], schema="identity")

    op.create_table(
        "otp_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index("idx_otp_phone", "otp_codes", ["phone"], schema="identity")

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("device_info", sa.String(length=200), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index("idx_refresh_user", "refresh_tokens", ["user_id"], schema="identity")
    # Not in the architecture's SQL, but every refresh looks a token up by its
    # hash and nothing else. Without this index that lookup is a sequential scan
    # over the busiest-growing table in the schema.
    op.create_index("idx_refresh_token_hash", "refresh_tokens", ["token_hash"], schema="identity")

    op.create_table(
        "user_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_table("user_status_history", schema="identity")
    op.drop_index("idx_refresh_token_hash", table_name="refresh_tokens", schema="identity")
    op.drop_index("idx_refresh_user", table_name="refresh_tokens", schema="identity")
    op.drop_table("refresh_tokens", schema="identity")
    op.drop_index("idx_otp_phone", table_name="otp_codes", schema="identity")
    op.drop_table("otp_codes", schema="identity")
    op.drop_index("idx_users_role", table_name="users", schema="identity")
    op.drop_index("idx_users_phone", table_name="users", schema="identity")
    op.drop_table("users", schema="identity")
    # The schema itself is left in place: dropping it would take anything else
    # created there with it, and an empty schema costs nothing.
