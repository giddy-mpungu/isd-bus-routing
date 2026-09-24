"""add minimum_buffer_minutes to optimization_settings

Revision ID: 3b7c1e9a4d20
Revises: 55c8a0eed01f
Create Date: 2026-09-24 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b7c1e9a4d20"
down_revision: str | None = "55c8a0eed01f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills an existing settings row with "no floor",
    # so behaviour doesn't change until an administrator sets one.
    op.add_column(
        "optimization_settings",
        sa.Column("minimum_buffer_minutes", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("optimization_settings", "minimum_buffer_minutes")
