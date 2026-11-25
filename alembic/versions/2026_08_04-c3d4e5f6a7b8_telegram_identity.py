"""store the verified Telegram chat used for OTP delivery

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        schema="identity",
    )
    op.create_index(
        "uq_users_telegram_user_id",
        "users",
        ["telegram_user_id"],
        unique=True,
        schema="identity",
    )
    op.create_index(
        "uq_users_telegram_chat_id",
        "users",
        ["telegram_chat_id"],
        unique=True,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("uq_users_telegram_chat_id", table_name="users", schema="identity")
    op.drop_index("uq_users_telegram_user_id", table_name="users", schema="identity")
    op.drop_column("users", "telegram_chat_id", schema="identity")
    op.drop_column("users", "telegram_user_id", schema="identity")
