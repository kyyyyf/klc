---
ticket: KLC-046
kind: design-options
authority: human
last_generated: 2026-06-24
---

# KLC-046 — Design options

## Context

Spec picked Option A (thin driver loop reusing existing skills, guardrails as explicit
pre-ack checks). This document records the loop shape and the guardrail set.

## Decision D-001: the loop

`autorunner.run(ticket, *, dispatch=None, max_auto=N) -> RunResult`:
1. Read state via `lifecycle.current_state`.
2. If `:work` — dispatch the phase agent (build → `build_orchestrator.run_build`; else
   `runner.run_agent`) with the resolved model; loop.
3. If `:ack-needed` — check guardrails; if any fires, pause+notify+log and stop. Else
   `collect_signals` + `evaluate`; on proceed, perform the `--auto` ack and increment the
   consecutive-auto counter; on pause, notify+log and stop.
4. If `:ack` — `klc next`; loop. If `archived` — done.

## Decision D-002: guardrails (checked before any auto-ack)

| Guardrail | Trigger | Action |
|---|---|---|
| irreversible/outward-facing | phase id `integrate`, or a pick whose label implies merge/push | always pause |
| budget ceiling | any `meta.budgets` counter at/over its limit | pause |
| consecutive-auto cap | `consecutive_auto_transitions` ≥ configured cap | pause |
| decision gate | pick gate == `decision` | pause (via gate_policy) |
| dirty signal | gate_policy returns pause | pause |
| dispatch failure | dispatched agent returned non-zero | pause at this `:work` |

All guardrails fail-closed: when in doubt, pause. The cap default lives in
`config/budgets.yml` as `consecutive_auto_transitions` (e.g. 6).

## Decision D-003: not a phase

`klc run` is a driver over the state machine, not a new phase in `phases.yml` (mirrors
KLC-044's advisory-not-phase decision). The runner only ever calls the same `ack --auto` /
`next` paths a human would, so it cannot reach a transition a human could not.

## Decision D-004: notifications + run log

Each pause emits a notification (stderr line + an optional `PushNotification` hook) and
appends to `.klc/tickets/<KEY>/run-log.md`: timestamped transitions, gate evaluations, and
the pause reason — so a human resuming sees the full trace.
