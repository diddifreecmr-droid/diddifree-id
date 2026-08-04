"""add language and profile photo URL to users

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language", sa.String(length=2), nullable=False, server_default=sa.text("'fr'")),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column("photo_url", sa.String(length=2048), nullable=True),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_column("users", "photo_url", schema="identity")
    op.drop_column("users", "language", schema="identity")
