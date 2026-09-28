"""student grade, eligibility flags, accommodations, home location, and
district transportation rules (spec sections 3, 3.1)

Revision ID: f1b9d3e7a284
Revises: e3c8a1f5d692
Create Date: 2026-09-28 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b9d3e7a284"
down_revision: str | None = "e3c8a1f5d692"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.add_column(sa.Column("grade", sa.String(length=3), nullable=True))
        batch.add_column(
            sa.Column(
                "needs_specialized_transport",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("hazardous_route", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_table(
        "student_accommodations",
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("qualification_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["qualification_id"], ["qualifications.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("student_id", "qualification_id"),
    )
    op.create_table(
        "student_homes",
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=False),
        sa.Column("location_lon", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("matched_address", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("student_id"),
    )
    op.create_table(
        "transportation_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("eligibility_miles", sa.Float(), nullable=False),
        *[
            sa.Column(f"walk_miles_{band}", sa.Float(), nullable=False)
            for band in ("prek", "elementary", "middle", "high", "specialized")
        ],
        *[
            sa.Column(f"ride_minutes_{band}", sa.Integer(), nullable=False)
            for band in ("prek", "elementary", "middle", "high", "specialized")
        ],
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("transportation_rules")
    op.drop_table("student_homes")
    op.drop_table("student_accommodations")
    with op.batch_alter_table("students") as batch:
        batch.drop_column("hazardous_route")
        batch.drop_column("needs_specialized_transport")
        batch.drop_column("grade")
