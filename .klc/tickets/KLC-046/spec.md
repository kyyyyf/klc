---
ticket: KLC-046
kind: feature
authority: human
last_generated: 2026-06-24
risk_tags: [autonomy]
---

# KLC-046 — Autonomous runner (Phase 6.2)

## Goals

Close the autonomy capstone: a `klc run <KEY>` loop that drives a ticket through the state
machine on its own — dispatching the phase agent at each `:work`, running the completion
gates, and applying the KLC-045 gate-policy to either auto-advance a clean `conditional`
gate or pause and notify. Bounded by guardrails so it can never silently take an
irreversible or risky action: a budget ceiling, a cap on consecutive auto-transitions,
mandatory pause on outward-facing/irreversible transitions, and a pause on any risk gate.

## Problem / Context

Phases 0–5 built trustworthy gates; KLC-045 added the policy that says which transitions are
safe to automate. What is missing is the driver that ties them together so a human is
bothered only at genuine decision points. The driver must reuse, not reinvent: KLC-042's
`build_orchestrator` already dispatches build steps to fresh subagents with the resolved
model; `runner.run_agent` dispatches a phase agent; `lifecycle` advances state; KLC-045's
`gate_policy` decides auto vs pause. The new surface is the loop and its guardrails. Because
the loop can, in principle, walk a ticket all the way to merge, the guardrails are the
safety-critical part: integrate/merge and any remote push must always pause, and the loop
must stop and notify on a budget ceiling or a run of too many consecutive auto-transitions
(a runaway backstop).

## Acceptance Criteria

- [ ] AC-1: `klc run <KEY>` reads the current state; at a `:work` state it dispatches the
  phase agent (build via KLC-042's orchestrator, others via `runner.run_agent`) with the
  resolved model, then re-reads state.
- [ ] AC-2: At `:ack-needed` it calls `gate_policy.collect_signals` + `evaluate`; on a clean
  `conditional` gate it auto-acks (via the KLC-045 `--auto` path) and continues; otherwise it
  pauses and emits a notification naming the reason.
- [ ] AC-3: A `decision` gate always pauses with a notification, even with clean signals.
- [ ] AC-4: Guardrails — the loop pauses (never proceeds) on: an integrate/merge transition
  or any step that would push to a remote; a budget ceiling reached; or a configurable cap of
  consecutive auto-transitions exceeded. Each pause states which guardrail fired.
- [ ] AC-5: Simulation tests drive the loop without human input, with agent dispatch faked
  and REAL lifecycle/`ack --auto`. TWO fixtures are required because the S track has NO
  `design` phase (design is tracks:[M,L] in phases.yml) — a clean S ticket walks
  build → review → integrate and its first stop is the integrate guardrail, never a design
  pick:
    - AC-5a (M or L fixture): the loop walks up to a `design:ack-needed` decision gate and
      HALTS there (decision gates never auto-ack), naming the reason.
    - AC-5b (S fixture): the loop walks build → review and HALTS at the integrate guardrail
      (integrate is the only outward/merge phase), naming the guardrail.
- [ ] AC-6: The runner writes a per-ticket run log (transitions taken, gates evaluated,
  pauses with reasons) so a human resuming after a pause sees exactly what happened.
- [ ] AC-7: Scope boundary — the runner is SINGLE-USER / feature-OFF only. If
  `state_feature.enabled()` is True (a multi-user `klc-state` worktree with an upstream),
  the runner refuses with a clear message and takes no transition. Multi-user autonomous
  running is out of scope: it would CAS-push every ack, need holder management, and need
  rc-1 sync-error disambiguation. Feature-off, `ack --auto` returns rc 0 (advanced) or rc 2
  (gate pause) and never the feature-on rc-1 sync errors, so the loop treats rc 0 = advanced,
  rc 2 = gate pause, and any other non-zero rc = an error pause with its own message.

## Non-goals

- Not adding an `autonomy` phase to `phases.yml`; the runner is a driver over the existing
  state machine (mirrors KLC-044's advisory-not-phase decision).
- Not changing gate logic or the gate-policy predicate; the runner orchestrates them.
- Not performing the merge itself; integrate always pauses for a human.
- Not supporting multi-user (state-feature-ON) autonomous runs — out of scope (AC-7). The
  runner refuses when `state_feature.enabled()` is True rather than guess at CAS-push /
  holder / rc-disambiguation semantics it does not implement.

## Audit reconciliation (2026-07 pre-build)

A pre-build audit against current code found and corrected these plan defects:

1. The loop must ADVANCE `:work → :ack-needed` itself. `:work → :ack-needed` happens INSIDE
   `klc ack` (via `phase_completion.can_complete`), not in `lifecycle`. So at `:work` the loop
   dispatches then calls `ack --auto`; a single `--auto` from `:work` auto-detects completion
   and walks `:work → :ack-needed → (gate)` in one call.
2. AC-5 was self-contradictory (an S ticket has no `design` phase). Split into AC-5a (M/L,
   design decision) and AC-5b (S, integrate guardrail). See AC-5.
3. The consecutive-auto cap has its OWN loader, kept OUT of `budget._load_limits()` (which
   reads `.klc/config/budgets.yml` and feeds `gate_policy.budget_overrun`).
4. Guardrail outward classification is by phase-id (`_OUTWARD_PHASES = {"integrate"}`), not a
   pick goto/label heuristic (no phases.yml pick label contains "push"; the substring
   heuristic was inert).
5. Feature-off scope boundary (AC-7) and rc disambiguation (AC-7) added.

## Approaches

- Option A — a thin driver loop over the existing skills, with guardrails as explicit
  pre-checks before each auto-ack:
  - Pros: maximal reuse (orchestrator, runner, lifecycle, gate_policy); the loop is small and
    the guardrails are auditable; no state-machine change; testable by injecting a fake
    dispatch and asserting the transition trace.
  - Cons: the loop must correctly classify "outward-facing" transitions — handled by a small
    explicit set plus the integrate phase id.
- Option B — embed auto-advance inside `lifecycle.apply_ack` itself:
  - Pros: one code path.
  - Cons: couples the safe-by-default manual state machine to autonomy; risks changing manual
    behaviour; harder to bound with guardrails. Rejected.
- Option C — an external shell script polling `klc status`:
  - Pros: no Python.
  - Cons: cannot reuse the orchestrator/gate_policy cleanly, no structured guardrails, brittle
    parsing. Rejected.

Picked: Option A — a thin in-process driver reusing the existing skills, guardrails as
explicit pre-ack checks. (DECISION D-001)

## Affected

- `core/skills/autorunner.py` (new) — the loop + guardrails + run log.
- `core/phases/run.py` (new), `scripts/klc` — the `klc run` verb.
- `core/skills/gate_policy.py` — consumed (from KLC-045); `build_orchestrator`, `runner`,
  `lifecycle` — consumed (from KLC-042 and core).
- `config/budgets.yml` — a `consecutive_auto_transitions` cap.
- `tests/integration/test_autorunner.py` (new).
- `docs/process.md` — document `klc run` and the guardrails.

## Estimate

| Axis | Score | Rationale |
|------|-------|-----------|
| complexity | 4 | A control loop coordinating dispatch, gates, policy, and guardrails. |
| uncertainty | 3 | Guardrail completeness (what counts as outward-facing) needs care. |
| risk | 3 | Can drive a ticket toward merge; guardrails are safety-critical. |
| manual | 2 | Manual dry-run on a real ticket before trusting it unattended. |
| total | 12 | L (new control loop, broad blast radius, irreversible-action surface). |
