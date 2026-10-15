"""add verified contact-link challenges

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-10-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enforce case-insensitive uniqueness at the database boundary. The
    # application normalizes new values too, but the database must protect
    # concurrent writes and pre-existing clients that bypass that convention.
    op.execute("DROP INDEX IF EXISTS identity.idx_users_email")
    op.execute(
        "CREATE UNIQUE INDEX idx_users_email ON identity.users (lower(email)) "
        "WHERE email IS NOT NULL",
    )
    op.create_table(
        "contact_link_challenges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_type", sa.String(length=10), nullable=False),
        sa.Column("target", sa.String(length=320), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index("idx_contact_link_user", "contact_link_challenges", ["user_id"], schema="identity")
    op.create_index(
        "idx_contact_link_target",
        "contact_link_challenges",
        ["contact_type", "target"],
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("idx_contact_link_target", table_name="contact_link_challenges", schema="identity")
    op.drop_index("idx_contact_link_user", table_name="contact_link_challenges", schema="identity")
    op.drop_table("contact_link_challenges", schema="identity")
    op.execute("DROP INDEX IF EXISTS identity.idx_users_email")
    op.create_index("idx_users_email", "users", ["email"], unique=True, schema="identity")
