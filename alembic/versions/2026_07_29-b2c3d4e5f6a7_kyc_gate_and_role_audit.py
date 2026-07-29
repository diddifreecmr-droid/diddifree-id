"""kyc gate and role audit

Moves the driver KYC gate into DiddiFreeID (architecture §7.5), before DiddiGo
starts its migration — once their accounts are here, changing the shape of the
role flow means coordinating with a live consumer.

Two additions:
  * `users.requested_role` — the role a module has asked for, awaiting decision.
    Nullable, so `IS NOT NULL` is the review queue.
  * `identity.user_role_history` — audit of role grants and refusals. Until now
    the `reason` documented on `PATCH /users/{id}/role` was accepted and thrown
    away, which made the contract's own example ("Validation KYC chauffeur
    DiddiGo, dossier #4021") unreadable after the fact.

The `pending_kyc` status itself needs no DDL: `status` is a VARCHAR and the
allowed values are enforced in the domain.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("requested_role", sa.String(length=20), nullable=True),
        schema="identity",
    )

    op.create_table(
        "user_role_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_role", sa.String(length=20), nullable=True),
        # NULL marks a refusal: the decision happened, no role was granted.
        sa.Column("to_role", sa.String(length=20), nullable=True),
        sa.Column("requested_role", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index("idx_role_history_user", "user_role_history", ["user_id"], schema="identity")


def downgrade() -> None:
    # Any account parked in `pending_kyc` would be left in a status the previous
    # revision's code does not know. Send them back to `pending_verification`:
    # they re-verify by OTP, which is recoverable, whereas an unknown status
    # value makes every one of their tokens unparseable.
    op.execute(
        "UPDATE identity.users SET status = 'pending_verification' WHERE status = 'pending_kyc'",
    )
    op.drop_index("idx_role_history_user", table_name="user_role_history", schema="identity")
    op.drop_table("user_role_history", schema="identity")
    op.drop_column("users", "requested_role", schema="identity")
