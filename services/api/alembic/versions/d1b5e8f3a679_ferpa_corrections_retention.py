"""FERPA: record correction requests and student withdrawal (for retention)

Revision ID: d1b5e8f3a679
Revises: c9a4d7e2f568
Create Date: 2026-10-07 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1b5e8f3a679"
down_revision: str | None = "c9a4d7e2f568"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("withdrawn_on", sa.Date(), nullable=True))
    op.create_table(
        "record_corrections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("what_is_wrong", sa.String(length=1000), nullable=False),
        sa.Column("should_say", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_record_corrections_student_id"), "record_corrections", ["student_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_record_corrections_student_id"), table_name="record_corrections")
    op.drop_table("record_corrections")
    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_column("withdrawn_on")
