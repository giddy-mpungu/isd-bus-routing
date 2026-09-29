"""stop proposals and minimum stop spacing (spec section 3.1)

Revision ID: b8e1f4a7c352
Revises: a6d2c8e4b173
Create Date: 2026-09-29 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e1f4a7c352"
down_revision: str | None = "a6d2c8e4b173"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transportation_rules") as batch:
        batch.add_column(
            sa.Column("min_stop_spacing_miles", sa.Float(), nullable=False, server_default="0.1")
        )
    op.create_table(
        "stop_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stop_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=False),
        sa.Column("location_lon", sa.Float(), nullable=False),
        sa.Column("student_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"]),
        sa.ForeignKeyConstraint(["stop_id"], ["stops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_stop_proposals_school_id"), "stop_proposals", ["school_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stop_proposals_school_id"), table_name="stop_proposals")
    op.drop_table("stop_proposals")
    with op.batch_alter_table("transportation_rules") as batch:
        batch.drop_column("min_stop_spacing_miles")
