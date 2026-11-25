"""add daily authenticated activity for identity reporting

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_activity_daily",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source", sa.String(length=40), server_default=sa.text("'authentication'"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index(
        "uq_user_activity_daily_user_day",
        "user_activity_daily",
        ["user_id", "activity_date"],
        unique=True,
        schema="identity",
    )
    op.create_index(
        "idx_user_activity_daily_date",
        "user_activity_daily",
        ["activity_date"],
        unique=False,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("idx_user_activity_daily_date", table_name="user_activity_daily", schema="identity")
    op.drop_index("uq_user_activity_daily_user_day", table_name="user_activity_daily", schema="identity")
    op.drop_table("user_activity_daily", schema="identity")
