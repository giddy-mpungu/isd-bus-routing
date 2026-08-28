# ADR 0005: Phase 1 hardening — capacity, real-routing estimator, observability

Status: Accepted
Date: 2026-08-25

## Context

The first Phase 1 cut proved the multi-school scheduling case but
deliberately left out passenger-capacity enforcement, used only a
straight-line deadhead estimator, and gave no visibility into *why*
the solver reached a given result short of reading return values in
code (pytest's default output is pass/fail only).

## Decision

- **Capacity (spec §15)**: `Vehicle.allowable_capacity()` (effective
  capacity if known, else nominal, else `None`) is checked as a hard
  constraint at candidate-crew-selection time, not inside the CP-SAT
  model — it's a static per-(job, crew) fact, not something that
  depends on the schedule. A vehicle with unknown capacity fails
  closed against any job that declares riders (`passenger_count > 0`);
  we do not treat "unknown" as "unlimited."
- **Real-routing deadhead estimator**: `osrm_deadhead_estimator` calls
  an OSRM-compatible HTTP API, with the HTTP call itself
  dependency-injected (`http_get` parameter) so the parsing/caching/
  error-handling logic is unit-testable without live network access —
  this sandbox's network allowlist doesn't include a routing API. It
  is explicitly documented as still not bus-legal routing (spec §6);
  that remains a Phase 6 concern. Failures either raise
  `DeadheadEstimationError` or use a caller-supplied `fallback`, logged
  at WARNING — never a silent, unlogged fallback, since a routing
  failure is operationally relevant.
- **Observability**: the scheduler now uses Python's standard
  `logging` (INFO for job/crew counts and outcomes, WARNING for
  infeasibility) instead of being a black box whose only output is its
  typed return value. Infeasibility reasons were made more specific —
  distinguishing "no crew qualified," "no crew available for this
  window," and "no crew has sufficient capacity" instead of one merged
  message — because a dispatcher or engineer debugging an infeasible
  case needs to know which constraint actually failed, per spec §21's
  explainability requirement applied to failures as well as successes.
- **Test suite tuning**: tests now solve with `num_search_workers=1`
  and a 2s time limit (toy problems don't benefit from CP-SAT's
  parallel search, and thread-pool startup overhead was the dominant
  cost), and `pytest.ini_options` sets `-v --durations=5` and
  `log_cli=true` so `pytest` output shows test names, the 5 slowest
  tests, and the solver's own log lines by default.

## Consequences

- `examples/run_worked_example.py` exists specifically to show a human
  the actual schedule and explanation text end-to-end — pytest answers
  "does the code still do what we expect," this script answers "what
  does it actually produce."
- Future hard constraints should follow the same pattern: static
  per-(job, crew) facts get checked during candidate filtering with a
  specific reason on failure; only constraints that genuinely depend on
  the relationship between multiple assignments belong in the CP-SAT
  model itself.
