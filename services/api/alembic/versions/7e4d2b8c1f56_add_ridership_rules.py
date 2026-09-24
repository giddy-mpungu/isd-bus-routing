"""add ridership_rules table

Revision ID: 7e4d2b8c1f56
Revises: 3b7c1e9a4d20
Create Date: 2026-09-24 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e4d2b8c1f56"
down_revision: str | None = "3b7c1e9a4d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ridership_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("am_cutoff_minute", sa.Integer(), nullable=True),
        sa.Column("pm_cutoff_minute", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ridership_rules")
