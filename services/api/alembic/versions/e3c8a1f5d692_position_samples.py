"""position history (spec sections 9, 20)

Every GPS report is also kept as a sample, for tracks and reports, and
deleted after settings.position_history_days.

Revision ID: e3c8a1f5d692
Revises: d7a3f9b2c541
Create Date: 2026-09-28 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3c8a1f5d692"
down_revision: str | None = "d7a3f9b2c541"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "position_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=False),
        sa.Column("location_lon", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crew_id", "recorded_at", name="uq_position_sample_crew_time"),
    )
    op.create_index(
        op.f("ix_position_samples_crew_id"), "position_samples", ["crew_id"], unique=False
    )
    op.create_index(
        op.f("ix_position_samples_recorded_at"), "position_samples", ["recorded_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_position_samples_recorded_at"), table_name="position_samples")
    op.drop_index(op.f("ix_position_samples_crew_id"), table_name="position_samples")
    op.drop_table("position_samples")
