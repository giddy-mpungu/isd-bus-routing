"""add student ridership tables (Phase 5 MVP)

Revision ID: 0ed51679129f
Revises: 7cd947c73878
Create Date: 2026-08-28 21:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0ed51679129f"
down_revision: str | None = "7cd947c73878"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=False),
        sa.Column("location_lon", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("stop_id", sa.Integer(), nullable=True),
        sa.Column(
            "default_ridership",
            sa.Enum(
                "RIDES",
                "DOES_NOT_RIDE",
                name="ridershipdefault",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"]),
        sa.ForeignKeyConstraint(["stop_id"], ["stops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "student_guardians",
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("student_id", "user_id"),
    )
    op.create_table(
        "ridership_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("AM", "PM", name="ridedirection", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("is_riding", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "student_id", "service_date", "direction", name="uq_ridership_override_leg"
        ),
    )
    # SQLite can't ALTER a constraint onto an existing table directly
    # (unlike the plain op.add_column calls in prior migrations, which
    # didn't need a constraint) — batch mode does a copy-and-move
    # instead, which works across all dialects Alembic supports here.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("student_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_student_id_students", "students", ["student_id"], ["id"]
        )
        batch_op.create_unique_constraint("uq_users_student_id", ["student_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_student_id", type_="unique")
        batch_op.drop_constraint("fk_users_student_id_students", type_="foreignkey")
        batch_op.drop_column("student_id")
    op.drop_table("ridership_overrides")
    op.drop_table("student_guardians")
    op.drop_table("students")
    op.drop_table("stops")
