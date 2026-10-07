"""Each user's chosen language (Spanish translation, Phase 5)

Revision ID: e2c6f9a4b781
Revises: d1b5e8f3a679
Create Date: 2026-10-07 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c6f9a4b781"
down_revision: str | None = "d1b5e8f3a679"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("preferred_language", sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("preferred_language")
