"""add geographic_knowledge_overrides table (Phase 6, spec section 8)

Revision ID: 7fd018832d67
Revises: 1797e7387b7a
Create Date: 2026-09-08 15:35:56.916364

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7fd018832d67"
down_revision: str | None = "1797e7387b7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geographic_knowledge_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=False),
        sa.Column("location_lon", sa.Float(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "FREQUENT_FLOODING",
                "DIFFICULT_INTERSECTION",
                "UNSAFE_TURN",
                "INVALID_TURNAROUND",
                "CONGESTION_WINDOW",
                "VEHICLE_SIZE_RESTRICTED",
                "PREFERRED_ENTRANCE",
                "OTHER",
                name="geographicknowledgecategory",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("geographic_knowledge_overrides")
