"""dispatch tasks (spec sections 11 and 14)

Unplanned work dispatch sends to a driver's tablet. Enum columns hold
enum names (SAEnum native_enum=False), so the status default is "SENT".

Revision ID: d7a3f9b2c541
Revises: b4e8d2a6c913
Create Date: 2026-09-28 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a3f9b2c541"
down_revision: str | None = "b4e8d2a6c913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dispatch_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("instructions", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="SENT", nullable=False),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dispatch_tasks_service_date"), "dispatch_tasks", ["service_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dispatch_tasks_service_date"), table_name="dispatch_tasks")
    op.drop_table("dispatch_tasks")
