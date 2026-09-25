"""add driver license_class and vehicle required_license_class

Spec section 15. Existing rows are backfilled so nothing becomes
unschedulable by accident (a driver whose codes name no class does,
deliberately: unknown fails closed):
  - drivers: the highest class named by their license qualification codes
    (CDL_A, CDL_B, CLASS_C / NON_CDL_C), else NULL (not on record);
  - vehicles: CDL_B when the capacity is 15+ passengers or unknown,
    else CLASS_C.

Revision ID: 9a1f3c5e7b20
Revises: 7e4d2b8c1f56
Create Date: 2026-09-24 20:00:00.000000

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a1f3c5e7b20"
down_revision: str | None = "7e4d2b8c1f56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUM = sa.Enum("CDL_A", "CDL_B", "CLASS_C", name="licenseclass", native_enum=False, length=16)
_RANK = {"CLASS_C": 1, "CDL_B": 2, "CDL_A": 3}
_CODES = {
    "CDLA": "CDL_A",
    "CDLB": "CDL_B",
    "CLASSC": "CLASS_C",
    "NONCDL": "CLASS_C",
    "NONCDLC": "CLASS_C",
    "CLASSCNONCDL": "CLASS_C",
}


def upgrade() -> None:
    op.add_column("drivers", sa.Column("license_class", _ENUM, nullable=True))
    op.add_column("vehicles", sa.Column("required_license_class", _ENUM, nullable=True))

    conn = op.get_bind()
    held: dict[int, str] = {}
    for driver_id, code in conn.execute(
        sa.text(
            "SELECT dq.driver_id, q.code FROM driver_qualifications dq "
            "JOIN qualifications q ON q.id = dq.qualification_id"
        )
    ):
        cls = _CODES.get(re.sub(r"[^A-Z]", "", code.upper()))
        if cls and _RANK[cls] > _RANK.get(held.get(driver_id, ""), 0):
            held[driver_id] = cls
    for driver_id, cls in held.items():
        conn.execute(
            sa.text("UPDATE drivers SET license_class = :c WHERE id = :i"),
            {"c": cls, "i": driver_id},
        )

    conn.execute(
        sa.text(
            "UPDATE vehicles SET required_license_class = CASE "
            "WHEN COALESCE(nominal_capacity, effective_capacity) IS NULL THEN 'CDL_B' "
            "WHEN COALESCE(nominal_capacity, effective_capacity) >= 15 THEN 'CDL_B' "
            "ELSE 'CLASS_C' END"
        )
    )
    with op.batch_alter_table("vehicles") as batch:
        batch.alter_column("required_license_class", existing_type=_ENUM, nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("required_license_class")
    with op.batch_alter_table("drivers") as batch:
        batch.drop_column("license_class")
