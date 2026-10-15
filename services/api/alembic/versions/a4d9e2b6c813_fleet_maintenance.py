"""Fleet maintenance: maintenance windows, service log, due dates, defect status

Revision ID: a4d9e2b6c813
Revises: f3a8c1d5e927
Create Date: 2026-10-15 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d9e2b6c813"
down_revision: str | None = "f3a8c1d5e927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.add_column(sa.Column("service_due_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("inspection_expires_on", sa.Date(), nullable=True))
    with op.batch_alter_table("driver_reports") as batch_op:
        batch_op.add_column(
            # Enum columns store the member's name: existing reports are OPEN.
            sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN")
        )
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("resolved_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("resolution_note", sa.String(length=500), nullable=True))
        batch_op.create_foreign_key(
            "fk_driver_reports_resolved_by_user_id", "users", ["resolved_by_user_id"], ["id"]
        )
    op.create_table(
        "maintenance_windows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("driver_report_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["driver_report_id"], ["driver_reports.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "service_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("work", sa.String(length=1000), nullable=False),
        sa.Column("performed_by", sa.String(length=255), nullable=False),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("service_records")
    op.drop_table("maintenance_windows")
    with op.batch_alter_table("driver_reports") as batch_op:
        batch_op.drop_constraint("fk_driver_reports_resolved_by_user_id", type_="foreignkey")
        batch_op.drop_column("resolution_note")
        batch_op.drop_column("resolved_by_user_id")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("status")
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.drop_column("inspection_expires_on")
        batch_op.drop_column("service_due_on")
