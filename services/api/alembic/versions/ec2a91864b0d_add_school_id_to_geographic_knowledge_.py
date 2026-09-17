"""add school_id to geographic knowledge overrides for preferred entrance

Revision ID: ec2a91864b0d
Revises: 0c40ce1336c6
Create Date: 2026-09-17 14:49:46.352169

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ec2a91864b0d"
down_revision: str | None = "0c40ce1336c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite can't ALTER a constraint onto an existing table directly --
    # batch mode does a copy-and-move instead (same precedent as
    # f60ed6405eec_add_school_id_to_announcements.py).
    with op.batch_alter_table("geographic_knowledge_overrides") as batch_op:
        batch_op.add_column(sa.Column("school_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_geographic_knowledge_overrides_school_id_schools", "schools", ["school_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("geographic_knowledge_overrides") as batch_op:
        batch_op.drop_constraint(
            "fk_geographic_knowledge_overrides_school_id_schools", type_="foreignkey"
        )
        batch_op.drop_column("school_id")
