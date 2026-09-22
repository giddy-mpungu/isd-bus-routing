"""add is_active to vehicles drivers qualifications

Revision ID: 55c8a0eed01f
Revises: ca18d1382748
Create Date: 2026-09-22 16:29:59.484660

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "55c8a0eed01f"
down_revision: str | None = "ca18d1382748"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills any pre-existing rows as active (the
    # Python-side model default only applies to new inserts); dropped
    # after backfill so it doesn't linger as an implicit schema default.
    op.add_column(
        "drivers", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "qualifications",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "vehicles", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    with op.batch_alter_table("drivers") as batch_op:
        batch_op.alter_column("is_active", server_default=None)
    with op.batch_alter_table("qualifications") as batch_op:
        batch_op.alter_column("is_active", server_default=None)
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.alter_column("is_active", server_default=None)


def downgrade() -> None:
    op.drop_column("vehicles", "is_active")
    op.drop_column("qualifications", "is_active")
    op.drop_column("drivers", "is_active")
