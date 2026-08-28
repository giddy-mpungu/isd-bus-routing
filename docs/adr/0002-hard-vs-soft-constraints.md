# ADR 0002: Hard vs. soft constraint representation

Status: Accepted
Date: 2026-08-25

## Context

Spec §2 requires a strict separation: hard constraints (capacity,
qualification, overlapping assignments, time-window feasibility, legal
work-hour rules) must never be violated by a returned solution. Soft
constraints (spec §2.2, e.g. minimize bus count, minimize ride time)
are objectives to trade off, weighted by district configuration.

## Decision

- Hard constraints are implemented as **CP-SAT model constraints**
  (`model.Add(...)`) — a solution that violates one is not in the
  feasible region at all. They are never expressed as penalty terms.
- Soft constraints are implemented as **weighted terms in the
  objective function**, with weights read from a per-district
  configuration object (never hardcoded), per spec §2.2 ("administrators
  should be able to configure the relative weights").
- If the solver returns `INFEASIBLE`, the system must say so plainly
  and require human intervention (relax which stops/runs are in scope,
  add a crew, etc.) — it must never silently degrade a hard constraint
  to get *a* solution. This directly implements spec §21 ("decision-
  support tool, not an autonomous authority").
- Every hard constraint added to the model is annotated with the spec
  section it implements, so `constraints.py` is auditable against the
  source spec line by line.

## Consequences

- The solver's public API always returns either a feasible
  `SchedulingResult` or an explicit `InfeasibleResult` with the
  reason — callers cannot accidentally treat a partial/relaxed
  solution as valid.
- Adding a new hard constraint later is a one-line addition to
  `constraints.py` with a spec citation, not a rewrite of the
  objective function.
