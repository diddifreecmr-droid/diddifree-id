"""add optional user email for email OTP delivery

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email", sa.String(length=320), nullable=True),
        schema="identity",
    )
    op.create_index(
        "idx_users_email",
        "users",
        ["email"],
        unique=True,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("idx_users_email", table_name="users", schema="identity")
    op.drop_column("users", "email", schema="identity")
