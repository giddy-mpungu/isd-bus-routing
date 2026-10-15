"""School bell schedules, special days and bus windows around the bells

Revision ID: f3a8c1d5e927
Revises: e2c6f9a4b781
Create Date: 2026-10-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a8c1d5e927"
down_revision: str | None = "e2c6f9a4b781"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OFFSETS = (
    "arrive_earliest_before",
    "arrive_latest_before",
    "leave_earliest_after",
    "leave_latest_after",
)


def upgrade() -> None:
    op.create_table(
        "bell_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("first_bell_minute", sa.Integer(), nullable=False),
        sa.Column("dismissal_minute", sa.Integer(), nullable=False),
        sa.Column("is_regular", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "name", name="uq_bell_schedule_name"),
    )
    op.create_table(
        "bell_calendar_days",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("bell_schedule_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bell_schedule_id"], ["bell_schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "service_date", name="uq_bell_calendar_day"),
    )
    op.create_table(
        "bell_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in _OFFSETS),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("schools") as batch_op:
        for name in _OFFSETS:
            batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))
    with op.batch_alter_table("route_templates") as batch_op:
        batch_op.add_column(
            sa.Column("follows_bells", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("route_templates") as batch_op:
        batch_op.drop_column("follows_bells")
    with op.batch_alter_table("schools") as batch_op:
        for name in _OFFSETS:
            batch_op.drop_column(name)
    op.drop_table("bell_rules")
    op.drop_table("bell_calendar_days")
    op.drop_table("bell_schedules")
