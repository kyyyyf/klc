---
ticket: KLC-045
kind: feature
authority: human
last_generated: 2026-06-24
risk_tags: []
---

# KLC-045 — Gate-policy layer (Phase 6.1)

## Goals

Classify every state-machine pick by how much human judgment it needs, and make that
classification machine-readable, so a future autonomous runner (KLC-046) can auto-advance
the safe transitions and pause on the ones that genuinely need a human. Concretely: add a
`gate` level to each pick in `phases.yml`, a pure predicate that decides whether a
`conditional` pick may auto-proceed given the current signals, and a hook that lets
`klc ack --auto` act on that predicate while leaving manual `klc ack` untouched.

## Problem / Context

`phases.yml` describes every phase and pick but says nothing about which transitions are
safe to automate. Today `klc ack` always requires a human (a `--pick` or the sole pick).
The roadmap's autonomy capstone needs a policy layer that distinguishes three kinds of
gate: `auto` (mechanical, no judgment — proceed silently), `conditional` (proceed only when
the existing safety signals are clean), and `decision` (irreducibly human — spec approval,
design pick, manual sign-off, merge — always pause). All the signals such a predicate needs
already exist as separate skills: `phase_completion` advisories, `scope_delta.compare`,
`scan_sentinels`, budget/mutation overruns in `meta.budgets`, the review verdict, and
`route_confidence` in meta. What is missing is (a) the per-pick classification and (b) a
predicate that combines the signals into an auto-proceed decision. This ticket adds exactly
those two things and wires them behind an opt-in flag; the autonomous loop that calls them
is KLC-046.

## Acceptance Criteria

- [ ] AC-1: The `Pick` dataclass (`core/skills/phases.py`) gains a `gate` field
  (`auto|conditional|decision`, default `decision`), parsed from `phases.yml`; an unknown
  value raises at load time (fail-closed).
- [ ] AC-2: Every pick in `phases.yml` carries an explicit `gate`. The decision gates are
  the spec approval (discovery / discovery-lite approve), the design pick, manual passed,
  and integrate merged; the rest are `conditional` or `auto` per the design.
- [ ] AC-3: `core/skills/gate_policy.py::evaluate(gate, signals) -> GateDecision` returns
  `proceed` for `auto`; `pause` for `decision`; for `conditional` it returns `proceed` only
  when every signal in `signals` is clean and `pause` (with reasons) otherwise.
- [ ] AC-4: A signal-collector `gate_policy.collect_signals(ticket, phase_id)` assembles ALL
  seven signals the roadmap 6.1 names — phase_completion advisory, scope expansion (scope_delta),
  sentinels (scan_sentinels), mutation, review verdict, route_confidence, and budget overrun —
  into the dict `evaluate` consumes, drawn from the real skills (no duplication). The `mutation`
  signal reads the `mutation_fix_attempts` budget counter (full mutation-score gating is deferred
  per KLC-044, so the signal is the counter, not a live score); this deferral is stated, not
  silently dropped. Any unavailable signal source yields a DIRTY value (fail-closed), never clean.
- [ ] AC-5: `klc ack <KEY> --auto` applies the policy: it auto-acks a `conditional` pick when
  signals are clean, and refuses (non-zero, naming the blocking reasons) when they are not or
  when the pick is a `decision`. Plain `klc ack` (no `--auto`) behaves exactly as today.
- [ ] AC-6: A `decision` pick is never auto-acked even with clean signals; a risk flag
  (scope expansion, sentinel hit, budget overrun, or low route_confidence) forces a pause on
  a `conditional` pick.

## Non-goals

- Not implementing the autonomous loop or notifications — that is KLC-046.
- Not changing what any existing gate checks; gate-policy only reads their outputs.
- Not auto-acking anything without the explicit `--auto` flag.

## Approaches

- Option A — data-driven `gate` field on picks plus a pure predicate over a collected
  signals dict, hooked behind `--auto` in `ack.py`:
  - Pros: the classification lives in `phases.yml` (single source, like the rest of the
    state machine); the predicate is a pure function (trivially unit-testable with synthetic
    signals); the collector reuses existing skills; manual flow is provably unchanged because
    the hook is behind a new flag.
  - Cons: two new surfaces (field + module) must stay consistent with the signal skills, but
    each is small and independently tested.
- Option B — hard-code the auto/decision classification in Python keyed by phase id:
  - Pros: no schema change.
  - Cons: re-introduces the "phase names hardcoded in Python" anti-pattern the state machine
    was designed to avoid; reshaping the process would need code edits. Rejected.
- Option C — a single monolithic `should_auto_ack(ticket)` that inlines every signal query:
  - Pros: one function.
  - Cons: not unit-testable without building full ticket fixtures for every signal; couples
    the policy to I/O; hard to reason about. Rejected in favour of pure-predicate + collector.

Picked: Option A — `gate` field + pure predicate + collector + opt-in flag. (DECISION D-001)

## Affected

- `core/skills/phases.py` — `gate` field on `Pick`, parsed and validated.
- `config/phases.yml` — a `gate` on every pick.
- `core/skills/gate_policy.py` (new) — `evaluate` + `collect_signals` + `GateDecision`.
- `core/phases/ack.py` — `--auto` flag applying the policy.
- `tests/integration/test_gate_policy.py` (new).
- `docs/process.md` — document the three gate levels.

## Estimate

| Axis | Score | Rationale |
|------|-------|-----------|
| complexity | 3 | A schema field, a pure predicate, a signal collector, and an ack hook. |
| uncertainty | 2 | The signal set is known; the only judgment is which picks are conditional vs auto. |
| risk | 2 | Touches the ack path, but behind an opt-in flag; manual flow unchanged. |
| manual | 1 | One manual dry-run of `--auto` on a clean and a risky ticket. |
| total | 8 | M (feature spanning skills, config, the ack verb, tests, docs). |
