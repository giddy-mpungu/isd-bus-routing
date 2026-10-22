"""The routing engine's turn costs

Revision ID: c3f8a4b6d692
Revises: b2e7f3a9c581
Create Date: 2026-10-22 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f8a4b6d692"
down_revision: str | None = "b2e7f3a9c581"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("turn_right_seconds", "5"),
    ("turn_sharp_right_seconds", "30"),
    ("turn_left_seconds", "20"),
    ("turn_sharp_left_seconds", "60"),
    ("turn_main_road_left_seconds", "60"),
)


def upgrade() -> None:
    with op.batch_alter_table("optimization_settings") as batch_op:
        for name, default in COLUMNS:
            batch_op.add_column(
                sa.Column(name, sa.Integer(), nullable=False, server_default=default)
            )


def downgrade() -> None:
    with op.batch_alter_table("optimization_settings") as batch_op:
        for name, _ in reversed(COLUMNS):
            batch_op.drop_column(name)
