"""HR employee ids for drivers; school attendance zones

Revision ID: e8b4c0d6f257
Revises: d7a3b9c5e146
Create Date: 2026-10-20 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b4c0d6f257"
down_revision: str | None = "d7a3b9c5e146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("drivers") as batch_op:
        batch_op.add_column(sa.Column("employee_id", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_drivers_employee_id", ["employee_id"])
    with op.batch_alter_table("schools") as batch_op:
        batch_op.add_column(sa.Column("zone_geojson", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("schools") as batch_op:
        batch_op.drop_column("zone_geojson")
    with op.batch_alter_table("drivers") as batch_op:
        batch_op.drop_constraint("uq_drivers_employee_id", type_="unique")
        batch_op.drop_column("employee_id")
