"""Ridership rules: a route lock before departure

Revision ID: f9c5d1e7a368
Revises: e8b4c0d6f257
Create Date: 2026-10-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9c5d1e7a368"
down_revision: str | None = "e8b4c0d6f257"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ridership_rules") as batch_op:
        batch_op.add_column(sa.Column("route_lock_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ridership_rules") as batch_op:
        batch_op.drop_column("route_lock_minutes")
