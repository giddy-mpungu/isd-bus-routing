"""add direction to runs table

Revision ID: b068fcf05a31
Revises: 8423e669ce9b
Create Date: 2026-09-14 12:07:58.900922

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b068fcf05a31"
down_revision: str | None = "8423e669ce9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills any pre-existing dev rows only (SQLite
    # requires a default to add a NOT NULL column to a populated
    # table) -- the Pydantic schema (RunCreate) keeps direction
    # required with no default, so every run created through the API
    # from here on must specify it explicitly.
    op.add_column(
        "runs",
        sa.Column(
            "direction",
            sa.Enum("AM", "PM", name="ridedirection", native_enum=False, length=8),
            nullable=False,
            server_default="AM",
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "direction")
