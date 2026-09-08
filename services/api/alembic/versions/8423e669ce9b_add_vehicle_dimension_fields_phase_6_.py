"""add vehicle dimension fields (Phase 6, spec section 6 slice 2)

Revision ID: 8423e669ce9b
Revises: 7fd018832d67
Create Date: 2026-09-08 16:34:31.981100

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8423e669ce9b"
down_revision: str | None = "7fd018832d67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("length_m", sa.Float(), nullable=True))
    op.add_column("vehicles", sa.Column("width_m", sa.Float(), nullable=True))
    op.add_column("vehicles", sa.Column("height_m", sa.Float(), nullable=True))
    op.add_column("vehicles", sa.Column("weight_kg", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "weight_kg")
    op.drop_column("vehicles", "height_m")
    op.drop_column("vehicles", "width_m")
    op.drop_column("vehicles", "length_m")
