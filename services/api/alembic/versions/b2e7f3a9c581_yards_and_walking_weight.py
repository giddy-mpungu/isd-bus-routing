"""Vehicle yards and the walking weight

Revision ID: b2e7f3a9c581
Revises: a1d6e2f8b479
Create Date: 2026-10-21 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e7f3a9c581"
down_revision: str | None = "a1d6e2f8b479"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.add_column(sa.Column("yard_lat", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("yard_lon", sa.Float(), nullable=True))
    with op.batch_alter_table("optimization_settings") as batch_op:
        batch_op.add_column(
            sa.Column("walking_weight", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("optimization_settings") as batch_op:
        batch_op.drop_column("walking_weight")
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.drop_column("yard_lon")
        batch_op.drop_column("yard_lat")
