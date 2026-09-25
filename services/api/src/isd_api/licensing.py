"""Driver license classes (spec sections 1, 2.1, 15): "only drivers legally
and organizationally qualified for a particular vehicle and assignment
should be eligible for scheduling".

The district's classes, as the spec names them: CDL Class A, CDL Class B,
and Class C non-CDL. They're tiered, as CDL classes are: a driver may drive
any vehicle whose required class is at or below their own, so CDL A drives
anything, CDL B drives B and C vehicles, and Class C only C vehicles.

Unknown fails closed, the same rule as capacity: a driver with no class on
record can't be paired with any vehicle, and a vehicle whose capacity is
unknown is treated as needing a CDL.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from isd_api.models import Driver, LicenseClass, Vehicle

_RANK = {LicenseClass.CLASS_C: 1, LicenseClass.CDL_B: 2, LicenseClass.CDL_A: 3}

LABELS = {
    LicenseClass.CDL_A: "CDL A",
    LicenseClass.CDL_B: "CDL B",
    LicenseClass.CLASS_C: "Class C (non-CDL)",
}

# A vehicle designed to carry 16 or more people including the driver needs
# a CDL (US federal definition), so 15+ passengers means CDL B by default.
CDL_PASSENGER_THRESHOLD = 15


def infer_required_class(
    nominal_capacity: int | None, effective_capacity: int | None
) -> LicenseClass:
    """A vehicle's default required class, from its passenger capacity.
    Unknown capacity is treated as needing a CDL (fail closed)."""
    capacity = nominal_capacity if nominal_capacity is not None else effective_capacity
    if capacity is None or capacity >= CDL_PASSENGER_THRESHOLD:
        return LicenseClass.CDL_B
    return LicenseClass.CLASS_C


_CODE_TO_CLASS = {
    "CDLA": LicenseClass.CDL_A,
    "CDLB": LicenseClass.CDL_B,
    "CLASSC": LicenseClass.CLASS_C,
    "NONCDL": LicenseClass.CLASS_C,
    "NONCDLC": LicenseClass.CLASS_C,
    "CLASSCNONCDL": LicenseClass.CLASS_C,
}


def license_class_from_codes(codes: Iterable[str]) -> LicenseClass | None:
    """The highest class named by a driver's license qualification codes
    (e.g. "CDL_B", "NON_CDL_C"), or None when none of them names one."""
    found = [
        _CODE_TO_CLASS[key]
        for key in (re.sub(r"[^A-Z]", "", code.upper()) for code in codes)
        if key in _CODE_TO_CLASS
    ]
    return max(found, key=_RANK.__getitem__) if found else None


def may_drive(held: LicenseClass | None, required: LicenseClass) -> bool:
    return held is not None and _RANK[held] >= _RANK[required]


def license_violation(driver: Driver, vehicle: Vehicle) -> str | None:
    """Why this driver may not drive this vehicle, or None if they may."""
    required = vehicle.required_license_class
    if may_drive(driver.license_class, required):
        return None
    held = LABELS[driver.license_class] if driver.license_class else "no license class on record"
    return (
        f"driver {driver.full_name} ({held}) isn't licensed for {vehicle.label}, "
        f"which needs {LABELS[required]}"
    )
