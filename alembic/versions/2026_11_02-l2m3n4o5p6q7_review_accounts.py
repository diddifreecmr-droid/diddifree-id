"""add the isolated Google Play review-account marker and audit history

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_review_account", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="identity",
    )
    op.create_table(
        "user_review_account_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_is_review_account", sa.Boolean(), nullable=False),
        sa.Column("to_is_review_account", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_by_client_id", sa.String(length=120), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index(
        "idx_review_account_history_user",
        "user_review_account_history",
        ["user_id"],
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_review_account_history_user",
        table_name="user_review_account_history",
        schema="identity",
    )
    op.drop_table("user_review_account_history", schema="identity")
    op.drop_column("users", "is_review_account", schema="identity")
