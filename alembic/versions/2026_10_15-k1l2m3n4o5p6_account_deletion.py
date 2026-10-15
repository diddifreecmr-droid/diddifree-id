"""add reversible account deletion and anonymisation fields

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-10-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column("deletion_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column("deletion_previous_status", sa.String(length=30), nullable=True),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="identity",
    )
    op.execute(
        "CREATE INDEX idx_users_deletion_due ON identity.users (deletion_scheduled_for) "
        "WHERE status = 'deletion_pending'",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS identity.idx_users_deletion_due")
    op.drop_column("users", "deleted_at", schema="identity")
    op.drop_column("users", "deletion_previous_status", schema="identity")
    op.drop_column("users", "deletion_scheduled_for", schema="identity")
    op.drop_column("users", "deletion_requested_at", schema="identity")
