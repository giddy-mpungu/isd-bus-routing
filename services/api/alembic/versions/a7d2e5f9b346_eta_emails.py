"""bus-time emails to families: opt-out flag and what was sent (Phase 5.5)

Revision ID: a7d2e5f9b346
Revises: f6c1d4e8a235
Create Date: 2026-10-01 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d2e5f9b346"
down_revision: str | None = "f6c1d4e8a235"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("eta_emails_enabled", sa.Boolean(), server_default=sa.true(), nullable=False)
        )
    op.create_table(
        "eta_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("eta_minute", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "student_id",
            "user_id",
            "service_date",
            "direction",
            "eta_minute",
            name="uq_eta_notification_once",
        ),
    )
    op.create_index(op.f("ix_eta_notifications_student_id"), "eta_notifications", ["student_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_eta_notifications_student_id"), table_name="eta_notifications")
    op.drop_table("eta_notifications")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("eta_emails_enabled")
