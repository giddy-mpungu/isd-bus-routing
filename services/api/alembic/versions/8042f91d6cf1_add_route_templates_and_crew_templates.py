"""add route_templates and crew_templates

Revision ID: 8042f91d6cf1
Revises: ec2a91864b0d
Create Date: 2026-09-21 13:24:07.024672

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8042f91d6cf1"
down_revision: str | None = "ec2a91864b0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crew_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("available_window_earliest", sa.Integer(), nullable=False),
        sa.Column("available_window_latest", sa.Integer(), nullable=False),
        sa.Column("days_of_week", sa.JSON(), nullable=False),
        sa.Column("active_from", sa.Date(), nullable=True),
        sa.Column("active_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "route_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("AM", "PM", name="ridedirection", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("window_earliest", sa.Integer(), nullable=False),
        sa.Column("window_latest", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), nullable=False),
        sa.Column("days_of_week", sa.JSON(), nullable=False),
        sa.Column("active_from", sa.Date(), nullable=True),
        sa.Column("active_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "route_template_required_qualifications",
        sa.Column("route_template_id", sa.Integer(), nullable=False),
        sa.Column("qualification_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["qualification_id"],
            ["qualifications.id"],
        ),
        sa.ForeignKeyConstraint(
            ["route_template_id"],
            ["route_templates.id"],
        ),
        sa.PrimaryKeyConstraint("route_template_id", "qualification_id"),
    )
    # Batch mode: SQLite can't ALTER TABLE ... ADD CONSTRAINT on an existing table.
    with op.batch_alter_table("crews") as batch_op:
        batch_op.add_column(sa.Column("crew_template_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_crews_crew_template_id_crew_templates",
            "crew_templates",
            ["crew_template_id"],
            ["id"],
        )
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("route_template_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_runs_route_template_id_route_templates",
            "route_templates",
            ["route_template_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_constraint("fk_runs_route_template_id_route_templates", type_="foreignkey")
        batch_op.drop_column("route_template_id")
    with op.batch_alter_table("crews") as batch_op:
        batch_op.drop_constraint("fk_crews_crew_template_id_crew_templates", type_="foreignkey")
        batch_op.drop_column("crew_template_id")
    op.drop_table("route_template_required_qualifications")
    op.drop_table("route_templates")
    op.drop_table("crew_templates")
