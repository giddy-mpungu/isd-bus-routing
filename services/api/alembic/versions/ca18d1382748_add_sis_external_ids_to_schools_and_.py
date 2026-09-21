"""add sis external ids to schools and students

Revision ID: ca18d1382748
Revises: 5fd30a0fa15d
Create Date: 2026-09-21 15:24:03.696081

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ca18d1382748"
down_revision: str | None = "5fd30a0fa15d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode: SQLite can't ALTER TABLE ... ADD CONSTRAINT on an existing table.
    with op.batch_alter_table("schools") as batch_op:
        batch_op.add_column(sa.Column("external_id", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_schools_external_id", ["external_id"])
    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("external_id", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_students_external_id", ["external_id"])


def downgrade() -> None:
    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_constraint("uq_students_external_id", type_="unique")
        batch_op.drop_column("external_id")
    with op.batch_alter_table("schools") as batch_op:
        batch_op.drop_constraint("uq_schools_external_id", type_="unique")
        batch_op.drop_column("external_id")
