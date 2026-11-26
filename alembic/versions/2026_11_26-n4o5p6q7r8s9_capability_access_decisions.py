"""add service-owned capability access decisions and audit

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-11-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_capabilities",
        sa.Column("last_access_event_id", sa.String(length=160), nullable=True),
        schema="identity",
    )
    op.add_column(
        "user_capabilities",
        sa.Column("access_reason", sa.Text(), nullable=True),
        schema="identity",
    )
    op.add_column(
        "user_capabilities",
        sa.Column("access_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="identity",
    )
    op.create_table(
        "user_capability_access_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service", sa.String(length=80), nullable=False),
        sa.Column("capability_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index(
        "idx_capability_access_history_user",
        "user_capability_access_history",
        ["user_id"],
        unique=False,
        schema="identity",
    )
    op.create_index(
        "uq_capability_access_history_event",
        "user_capability_access_history",
        ["user_id", "service", "capability_type", "event_id"],
        unique=True,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_capability_access_history_event",
        table_name="user_capability_access_history",
        schema="identity",
    )
    op.drop_index(
        "idx_capability_access_history_user",
        table_name="user_capability_access_history",
        schema="identity",
    )
    op.drop_table("user_capability_access_history", schema="identity")
    op.drop_column("user_capabilities", "access_updated_at", schema="identity")
    op.drop_column("user_capabilities", "access_reason", schema="identity")
    op.drop_column("user_capabilities", "last_access_event_id", schema="identity")
