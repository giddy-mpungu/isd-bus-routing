"""assignment lifecycle states (spec section 14)

"scheduled" becomes "sent", the first state of
Sent -> Received -> Acknowledged -> En Route -> Arrived -> In Progress -> Completed.
The column is a plain VARCHAR(20) holding enum names, so only data and
the server default change. (The original migration's server default was
lowercase "scheduled"; both spellings are converted.)

Revision ID: b4e8d2a6c913
Revises: 9a1f3c5e7b20
Create Date: 2026-09-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e8d2a6c913"
down_revision: str | None = "9a1f3c5e7b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE assignments SET status = 'SENT' WHERE status IN ('SCHEDULED', 'scheduled')")
    with op.batch_alter_table("assignments") as batch:
        batch.alter_column(
            "status", existing_type=sa.String(20), server_default="SENT", existing_nullable=False
        )


def downgrade() -> None:
    # The finer-grained states have no equivalent in the old model; anything
    # not yet underway or finished goes back to "scheduled".
    op.execute(
        "UPDATE assignments SET status = 'SCHEDULED' "
        "WHERE status IN ('SENT', 'RECEIVED', 'ACKNOWLEDGED')"
    )
    op.execute(
        "UPDATE assignments SET status = 'IN_PROGRESS' WHERE status IN ('EN_ROUTE', 'ARRIVED')"
    )
    with op.batch_alter_table("assignments") as batch:
        batch.alter_column(
            "status",
            existing_type=sa.String(20),
            server_default="scheduled",
            existing_nullable=False,
        )
