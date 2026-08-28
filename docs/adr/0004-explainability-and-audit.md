# ADR 0004: Explainability and audit trail

Status: Accepted
Date: 2026-08-25

## Context

Spec §21 requires the optimizer to explain major recommendations in
terms a transportation administrator can evaluate (e.g. "Bus 142 was
assigned Routes E12, H07, and M18 because the assignments do not
overlap, vehicle capacity is sufficient, the driver is qualified, and
12 minutes of operational buffer remain"). Spec §14 requires an audit
trail of material assignment changes.

## Decision

- Every `Assignment` the solver produces carries a structured
  `Explanation` object (not just free text) capturing: which hard
  constraints were checked and passed, the buffer/slack remaining
  against each relevant constraint, and which soft-objective terms it
  contributed to. Human-readable text is generated *from* this
  structure, not authored ad hoc — this keeps explanations accurate by
  construction rather than a separate string that can drift from the
  actual computed values.
- Explanations are computed at solve time (we have the model's
  intermediate values then), not reconstructed after the fact from the
  final schedule alone.
- Audit trail (Phase 2+) is an append-only log of assignment state
  transitions, keyed by who/what triggered the change (dispatcher
  action, driver absence event, automatic reoptimization), separate
  from the operational tables so it can't be edited by normal writes.

## Consequences

- `explain.py` has no independent source of truth about *why* an
  assignment was made — it only formats what the constraint/objective
  evaluation already computed, so an explanation can never claim a
  buffer or qualification that the solver didn't actually check.
