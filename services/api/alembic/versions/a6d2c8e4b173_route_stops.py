"""ordered stops on recurring routes (spec sections 3, 9)

Revision ID: a6d2c8e4b173
Revises: f1b9d3e7a284
Create Date: 2026-09-29 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6d2c8e4b173"
down_revision: str | None = "f1b9d3e7a284"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "route_stops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("route_template_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("stop_id", sa.Integer(), nullable=False),
        sa.Column("minutes_from_start", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["route_template_id"], ["route_templates.id"]),
        sa.ForeignKeyConstraint(["stop_id"], ["stops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_template_id", "position", name="uq_route_stop_position"),
        sa.UniqueConstraint("route_template_id", "stop_id", name="uq_route_stop_once"),
    )
    op.create_index(op.f("ix_route_stops_route_template_id"), "route_stops", ["route_template_id"])
    op.create_index(op.f("ix_route_stops_stop_id"), "route_stops", ["stop_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_route_stops_stop_id"), table_name="route_stops")
    op.drop_index(op.f("ix_route_stops_route_template_id"), table_name="route_stops")
    op.drop_table("route_stops")
