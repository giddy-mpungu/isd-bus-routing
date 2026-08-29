"""add driver_absences table (Phase 6 first slice)

Revision ID: 1797e7387b7a
Revises: 0ed51679129f
Create Date: 2026-08-28 22:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1797e7387b7a"
down_revision: str | None = "0ed51679129f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "driver_absences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "SICK_LEAVE",
                "PERSONAL_DAY",
                "VACATION",
                "EMERGENCY_LEAVE",
                "TRAINING",
                "APPROVED_LEAVE",
                "ADMINISTRATIVE_DIRECTION",
                "INJURY",
                "NO_CALL_NO_SHOW",
                "OTHER",
                name="absencereason",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("driver_absences")
