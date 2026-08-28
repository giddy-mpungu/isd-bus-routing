"""add status to assignments

Revision ID: 079577497cd4
Revises: 90c23b4aa064
Create Date: 2026-08-28 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "079577497cd4"
down_revision: str | None = "90c23b4aa064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default so existing rows start as "scheduled" (the correct
    # starting state — no driver has reported progress yet), same
    # reasoning as the `locked` column's server_default in 90c23b4aa064.
    op.add_column(
        "assignments",
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
    )
    op.add_column(
        "assignments",
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assignments", "status_updated_at")
    op.drop_column("assignments", "status")
