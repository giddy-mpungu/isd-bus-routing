"""add vehicle_positions table

Revision ID: 67d40ff5347f
Revises: b068fcf05a31
Create Date: 2026-09-14 12:35:14.767633

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "67d40ff5347f"
down_revision: str | None = "b068fcf05a31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=False),
        sa.Column("location_lon", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crew_id", name="uq_vehicle_position_one_per_crew"),
    )


def downgrade() -> None:
    op.drop_table("vehicle_positions")
