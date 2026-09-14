"""add field_trips table

Revision ID: 85f9f179cec0
Revises: 67d40ff5347f
Create Date: 2026-09-14 12:58:43.642498

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85f9f179cec0"
down_revision: str | None = "67d40ff5347f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_trips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requesting_party", sa.String(length=255), nullable=False),
        sa.Column("origin", sa.String(length=255), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=False),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_return_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_return_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("passenger_count", sa.Integer(), nullable=False),
        sa.Column("assigned_driver_id", sa.Integer(), nullable=True),
        sa.Column("assigned_vehicle_id", sa.Integer(), nullable=True),
        sa.Column("bus_assistant_name", sa.String(length=255), nullable=True),
        sa.Column("trip_contact", sa.String(length=255), nullable=False),
        sa.Column("special_instructions", sa.String(length=1000), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "REQUESTED",
                "APPROVED",
                "ASSIGNED",
                "DISPATCHED",
                "IN_PROGRESS",
                "RETURNING",
                "COMPLETED",
                name="tripstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_driver_id"], ["drivers.id"]),
        sa.ForeignKeyConstraint(["assigned_vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "field_trip_required_qualifications",
        sa.Column("field_trip_id", sa.Integer(), nullable=False),
        sa.Column("qualification_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["field_trip_id"], ["field_trips.id"]),
        sa.ForeignKeyConstraint(["qualification_id"], ["qualifications.id"]),
        sa.PrimaryKeyConstraint("field_trip_id", "qualification_id"),
    )


def downgrade() -> None:
    op.drop_table("field_trip_required_qualifications")
    op.drop_table("field_trips")
