"""register service clients for client-credentials tokens

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=120), nullable=False),
        sa.Column("service_name", sa.String(length=80), nullable=False),
        sa.Column("environment", sa.String(length=30), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "allowed_audiences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "allowed_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index(
        "uq_service_clients_client_id",
        "service_clients",
        ["client_id"],
        unique=True,
        schema="identity",
    )
    op.create_index(
        "idx_service_clients_service_environment",
        "service_clients",
        ["service_name", "environment"],
        unique=False,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("idx_service_clients_service_environment", table_name="service_clients", schema="identity")
    op.drop_index("uq_service_clients_client_id", table_name="service_clients", schema="identity")
    op.drop_table("service_clients", schema="identity")
