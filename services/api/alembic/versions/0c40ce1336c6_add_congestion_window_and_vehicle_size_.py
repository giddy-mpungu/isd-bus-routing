"""add congestion window and vehicle size restriction fields to geographic knowledge overrides

Revision ID: 0c40ce1336c6
Revises: f60ed6405eec
Create Date: 2026-09-17 14:21:13.063247

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c40ce1336c6"
down_revision: str | None = "f60ed6405eec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "geographic_knowledge_overrides",
        sa.Column("window_start_minute", sa.Integer(), nullable=True),
    )
    op.add_column(
        "geographic_knowledge_overrides",
        sa.Column("window_end_minute", sa.Integer(), nullable=True),
    )
    op.add_column(
        "geographic_knowledge_overrides",
        sa.Column(
            "restricted_dimension",
            sa.Enum(
                "LENGTH_M",
                "WIDTH_M",
                "HEIGHT_M",
                "WEIGHT_KG",
                name="restrictedvehicledimension",
                native_enum=False,
                length=16,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "geographic_knowledge_overrides", sa.Column("max_allowed_value", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("geographic_knowledge_overrides", "max_allowed_value")
    op.drop_column("geographic_knowledge_overrides", "restricted_dimension")
    op.drop_column("geographic_knowledge_overrides", "window_end_minute")
    op.drop_column("geographic_knowledge_overrides", "window_start_minute")
