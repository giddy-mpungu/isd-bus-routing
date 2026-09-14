"""add driver_reports table

Revision ID: 98bf862cff59
Revises: 936d32fa05b0
Create Date: 2026-09-14 13:57:53.742118

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "98bf862cff59"
down_revision: str | None = "936d32fa05b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "driver_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column(
            "report_type",
            sa.Enum(
                "INCIDENT",
                "VEHICLE_DEFECT",
                name="driverreporttype",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("driver_reports")
