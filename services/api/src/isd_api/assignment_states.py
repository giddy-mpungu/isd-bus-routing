"""The assignment lifecycle (spec section 14):

    Sent -> Received -> Acknowledged -> En Route -> Arrived -> In Progress -> Completed

plus No-show, a terminal state reachable from any unfinished one. A driver
only moves an assignment forward; skipping ahead is fine (a driver may go
straight from Acknowledged to In Progress), going back isn't. A dispatcher
may set any state, to correct a mistake. Handing an unfinished assignment
to a different driver sends it again, so the new driver has to receive and
acknowledge it themselves.
"""

from __future__ import annotations

from isd_api.models import AssignmentStatus

S = AssignmentStatus

LIFECYCLE: list[AssignmentStatus] = [
    S.SENT,
    S.RECEIVED,
    S.ACKNOWLEDGED,
    S.EN_ROUTE,
    S.ARRIVED,
    S.IN_PROGRESS,
    S.COMPLETED,
]
TERMINAL = {S.COMPLETED, S.NO_SHOW}
# Past the point where a hand-over resets anything: the bus is moving.
UNDERWAY = {S.EN_ROUTE, S.ARRIVED, S.IN_PROGRESS}

LABELS = {
    S.SENT: "Sent",
    S.RECEIVED: "Received",
    S.ACKNOWLEDGED: "Acknowledged",
    S.EN_ROUTE: "En route",
    S.ARRIVED: "Arrived",
    S.IN_PROGRESS: "In progress",
    S.COMPLETED: "Completed",
    S.NO_SHOW: "No-show",
}


def driver_transition_problem(current: AssignmentStatus, target: AssignmentStatus) -> str | None:
    """Why a driver can't move an assignment from `current` to `target`,
    or None if they can."""
    if current == target:
        return None
    if current in TERMINAL:
        return f"This assignment is already {LABELS[current].lower()}."
    if target == S.NO_SHOW:
        return None
    if target == S.SENT:
        return "Only dispatch can send an assignment again."
    if LIFECYCLE.index(target) < LIFECYCLE.index(current):
        return (
            f"Can't go back from {LABELS[current].lower()} to {LABELS[target].lower()}. "
            "Ask dispatch to correct it."
        )
    return None


def resets_on_new_driver(current: AssignmentStatus) -> bool:
    """Whether handing this assignment to a different driver sends it again."""
    return current not in TERMINAL and current not in UNDERWAY
