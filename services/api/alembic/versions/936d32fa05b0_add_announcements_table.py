"""add announcements table

Revision ID: 936d32fa05b0
Revises: 85f9f179cec0
Create Date: 2026-09-14 13:34:06.234059

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "936d32fa05b0"
down_revision: str | None = "85f9f179cec0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "GENERAL",
                "DELAY",
                "SUBSTITUTION",
                "ROUTE_CHANGE",
                name="announcementcategory",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "audience",
            sa.Enum(
                "ALL", "FAMILY", "DRIVER", name="announcementaudience", native_enum=False, length=10
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("announcements")
