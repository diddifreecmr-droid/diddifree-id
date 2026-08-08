"""allow email-only identity and OTP verification

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "phone", existing_type=sa.String(length=20), nullable=True, schema="identity")
    op.alter_column("otp_codes", "phone", existing_type=sa.String(length=20), nullable=True, schema="identity")
    op.add_column(
        "otp_codes",
        sa.Column("email", sa.String(length=320), nullable=True),
        schema="identity",
    )
    op.create_index("idx_otp_email", "otp_codes", ["email"], schema="identity")


def downgrade() -> None:
    op.drop_index("idx_otp_email", table_name="otp_codes", schema="identity")
    op.drop_column("otp_codes", "email", schema="identity")
    op.alter_column("otp_codes", "phone", existing_type=sa.String(length=20), nullable=False, schema="identity")
    op.alter_column("users", "phone", existing_type=sa.String(length=20), nullable=False, schema="identity")
