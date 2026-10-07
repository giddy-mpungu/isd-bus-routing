"""FERPA: who at the district viewed a student's information

Revision ID: c9a4d7e2f568
Revises: b8f3c6a1d457
Create Date: 2026-10-07 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a4d7e2f568"
down_revision: str | None = "b8f3c6a1d457"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_access_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("what", sa.String(length=32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "user_id", "what", "day", name="uq_student_access_daily"),
    )
    op.create_index(op.f("ix_student_access_log_student_id"), "student_access_log", ["student_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_student_access_log_student_id"), table_name="student_access_log")
    op.drop_table("student_access_log")
