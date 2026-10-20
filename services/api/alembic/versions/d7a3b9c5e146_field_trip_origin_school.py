"""Field trips: the school a trip leaves from

Revision ID: d7a3b9c5e146
Revises: c6f2a8b4d035
Create Date: 2026-10-20 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a3b9c5e146"
down_revision: str | None = "c6f2a8b4d035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("field_trips") as batch_op:
        batch_op.add_column(sa.Column("origin_school_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_field_trips_origin_school_id", "schools", ["origin_school_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("field_trips") as batch_op:
        batch_op.drop_constraint("fk_field_trips_origin_school_id", type_="foreignkey")
        batch_op.drop_column("origin_school_id")
