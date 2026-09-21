"""add the DiddiFree Pro capability projection

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-09-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_capabilities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service", sa.String(length=80), nullable=False),
        sa.Column("capability_type", sa.String(length=80), nullable=False),
        sa.Column("access_status", sa.String(length=20), server_default=sa.text("'requested'"), nullable=False),
        sa.Column("operational_status", sa.String(length=80), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("status_source", sa.String(length=80), server_default=sa.text("'diddifreeid'"), nullable=False),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("projection_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_event_id", sa.String(length=160), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index(
        "uq_user_capabilities_user_service_type",
        "user_capabilities",
        ["user_id", "service", "capability_type"],
        unique=True,
        schema="identity",
    )
    op.create_index(
        "idx_user_capabilities_user",
        "user_capabilities",
        ["user_id"],
        unique=False,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("idx_user_capabilities_user", table_name="user_capabilities", schema="identity")
    op.drop_index("uq_user_capabilities_user_service_type", table_name="user_capabilities", schema="identity")
    op.drop_table("user_capabilities", schema="identity")
