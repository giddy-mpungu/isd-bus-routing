"""add destination_profiles table and field_trips.destination_profile_id

Revision ID: 7376c8a6c829
Revises: 98bf862cff59
Create Date: 2026-09-15 17:15:46.356190

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7376c8a6c829"
down_revision: str | None = "98bf862cff59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "destination_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=True),
        sa.Column("location_lon", sa.Float(), nullable=True),
        sa.Column("approved_entrance", sa.String(length=500), nullable=True),
        sa.Column("parking_notes", sa.String(length=500), nullable=True),
        sa.Column("turn_restrictions", sa.String(length=500), nullable=True),
        sa.Column("driver_notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # SQLite can't ALTER a constraint onto an existing table directly --
    # batch mode does a copy-and-move instead (same precedent as
    # 0ed51679129f_add_student_ridership_tables.py's users.student_id).
    with op.batch_alter_table("field_trips") as batch_op:
        batch_op.add_column(sa.Column("destination_profile_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_field_trips_destination_profile_id_destination_profiles",
            "destination_profiles",
            ["destination_profile_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("field_trips") as batch_op:
        batch_op.drop_constraint(
            "fk_field_trips_destination_profile_id_destination_profiles", type_="foreignkey"
        )
        batch_op.drop_column("destination_profile_id")
    op.drop_table("destination_profiles")
