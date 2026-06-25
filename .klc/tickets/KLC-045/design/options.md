---
ticket: KLC-045
kind: design-options
authority: human
last_generated: 2026-06-24
---

# KLC-045 — Design options

## Context

Spec picked Option A (data-driven `gate` field + pure predicate + collector + `--auto`
hook). This document records the gate classification and the predicate contract.

## Decision D-001: per-pick gate classification

| Phase / pick | Gate | Rationale |
|---|---|---|
| intake confirm-route | conditional | route confidence is a signal; clean high-confidence routes can auto-advance |
| discovery / discovery-lite approve | **decision** | spec approval is irreducibly human |
| acceptance-test-plan / detailed-test-plan approve | conditional | mechanical completeness already gated |
| design pick (option-A/B/C) | **decision** | choosing the approach is human judgment |
| build approve | conditional | Evidence + per-step review + TDD gates already enforce mechanics |
| review approve | conditional | verdict signal gates it; request-changes is decision |
| manual passed | **decision** | human sign-off by definition |
| integrate merged | **decision** | irreversible / outward-facing |
| observe clean | conditional | regression/rollback are decision |
| learn archive | conditional | terminal bookkeeping |
| any needs-rework / request-changes / failed / regression / rollback | decision | choosing to go back is human |

## Decision D-002: predicate contract

`evaluate(gate, signals) -> GateDecision(proceed: bool, reasons: list[str])`:
- `auto` → always proceed.
- `decision` → always pause (reason: "decision gate — human required").
- `conditional` → proceed only when every signal is clean; otherwise pause with one reason
  per dirty signal.

A signal is "clean" when: advisory is empty, scope has no expansion, no sentinel hits, no
budget overrun, verdict is approve-equivalent, route_confidence is not "low". An
unavailable signal counts as dirty (fail-closed).

## Decision D-003: opt-in hook

`klc ack --auto` is the only caller in this ticket. Without `--auto`, `ack.py` is unchanged.
With `--auto` at `:ack-needed`, it resolves the forced/sole pick, collects signals, calls
`evaluate`, and either performs the ack or exits non-zero printing the reasons. KLC-046's
runner will call the same path.
