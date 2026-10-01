"""two-step sign-in: authenticator secrets and recovery codes (Phase 5.3)

Revision ID: e5b9c3d7f124
Revises: d4a8b2c6e913
Create Date: 2026-09-30 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b9c3d7f124"
down_revision: str | None = "d4a8b2c6e913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("mfa_secret_encrypted", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("mfa_pending_secret_encrypted", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(sa.Column("mfa_last_step", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mfa_recovery_codes_user_id"), "mfa_recovery_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_mfa_recovery_codes_user_id"), table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("mfa_enabled_at")
        batch_op.drop_column("mfa_last_step")
        batch_op.drop_column("mfa_pending_secret_encrypted")
        batch_op.drop_column("mfa_secret_encrypted")
