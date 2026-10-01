"""single sign-on: the provider's subject id per user (Phase 5.4)

Revision ID: f6c1d4e8a235
Revises: e5b9c3d7f124
Create Date: 2026-10-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6c1d4e8a235"
down_revision: str | None = "e5b9c3d7f124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("oidc_subject", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint("uq_users_oidc_subject", ["oidc_subject"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_oidc_subject", type_="unique")
        batch_op.drop_column("oidc_subject")
