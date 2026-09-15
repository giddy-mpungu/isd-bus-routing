"""add school_id to announcements

Revision ID: f60ed6405eec
Revises: 7376c8a6c829
Create Date: 2026-09-15 17:36:15.076158

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f60ed6405eec"
down_revision: str | None = "7376c8a6c829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite can't ALTER a constraint onto an existing table directly --
    # batch mode does a copy-and-move instead (same precedent as
    # 7376c8a6c829_add_destination_profiles_table's field_trips column).
    with op.batch_alter_table("announcements") as batch_op:
        batch_op.add_column(sa.Column("school_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_announcements_school_id_schools", "schools", ["school_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("announcements") as batch_op:
        batch_op.drop_constraint("fk_announcements_school_id_schools", type_="foreignkey")
        batch_op.drop_column("school_id")
