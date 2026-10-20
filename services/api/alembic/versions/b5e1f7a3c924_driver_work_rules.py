"""Driver work-hour rules (duty limit, breaks, rest) and a ride-time weight

Revision ID: b5e1f7a3c924
Revises: a4d9e2b6c813
Create Date: 2026-10-20 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e1f7a3c924"
down_revision: str | None = "a4d9e2b6c813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("max_duty_minutes", "break_after_minutes", "break_minutes", "min_rest_minutes")


def upgrade() -> None:
    # All null: off until the district enters its own limits.
    with op.batch_alter_table("optimization_settings") as batch_op:
        for name in _COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("ride_time_weight", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("optimization_settings") as batch_op:
        batch_op.drop_column("ride_time_weight")
        for name in reversed(_COLUMNS):
            batch_op.drop_column(name)
