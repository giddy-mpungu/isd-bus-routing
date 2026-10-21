"""Kinds of route, run and trip; a route's buffer by reason

Revision ID: a1d6e2f8b479
Revises: f9c5d1e7a368
Create Date: 2026-10-21 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1d6e2f8b479"
down_revision: str | None = "f9c5d1e7a368"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum columns store the member's name: existing ones are REGULAR / FIELD_TRIP.
    with op.batch_alter_table("route_templates") as batch_op:
        batch_op.add_column(sa.Column("buffer_breakdown", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("kind", sa.String(length=24), nullable=False, server_default="REGULAR")
        )
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.String(length=24), nullable=False, server_default="REGULAR")
        )
    with op.batch_alter_table("field_trips") as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="FIELD_TRIP")
        )


def downgrade() -> None:
    with op.batch_alter_table("field_trips") as batch_op:
        batch_op.drop_column("kind")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("kind")
    with op.batch_alter_table("route_templates") as batch_op:
        batch_op.drop_column("kind")
        batch_op.drop_column("buffer_breakdown")
