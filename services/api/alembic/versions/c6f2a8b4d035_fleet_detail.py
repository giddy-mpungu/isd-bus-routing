"""Fleet detail: vehicle type, wheelchair positions, turning radius

Revision ID: c6f2a8b4d035
Revises: b5e1f7a3c924
Create Date: 2026-10-20 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6f2a8b4d035"
down_revision: str | None = "b5e1f7a3c924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.add_column(sa.Column("vehicle_type", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("wheelchair_positions", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("turning_radius_m", sa.Float(), nullable=True))
    with op.batch_alter_table("qualifications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "takes_wheelchair_position",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("qualifications") as batch_op:
        batch_op.drop_column("takes_wheelchair_position")
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.drop_column("turning_radius_m")
        batch_op.drop_column("wheelchair_positions")
        batch_op.drop_column("vehicle_type")
