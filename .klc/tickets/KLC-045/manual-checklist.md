---
ticket: KLC-045
kind: manual-checklist
authority: human
---

# Manual checklist — KLC-045

## Checks

- [x] `config/phases.yml` — every pick block has an explicit `gate:` field. Value is one
  of `auto`, `conditional`, or `decision`. Verified by `test_every_pick_has_gate`.
- [x] `core/skills/gate_policy.py` exists. `evaluate("auto", {})` returns `GateDecision(True)`;
  `evaluate("decision", {})` returns `GateDecision(False)`; `evaluate("conditional", {})` with
  a missing key returns `GateDecision(False)`. Verified by step-2 tests.
- [x] `klc ack KLC-045 --auto` flag accepted by the CLI (checked via argparse help and
  `test_ack_auto_proceeds_clean` test).
- [x] A decision-gate pick never auto-acks even with all-clean signals (`test_decision_never_auto`).
- [x] Dirty signal (scope expansion) causes `--auto` to print reasons and exit 2, leaving
  phase unchanged (`test_ack_auto_refuses_risky`).
- [x] Pre-review phases return `"N/A"` for verdict in `collect_signals` — build-phase
  auto-ack is not blocked by missing review-report (`test_collect_signals_pre_review_verdict_na`).
- [x] All 17 gate-policy tests pass. Full suite (475 tests) passes.
- [x] `docs/process.md` has "Gate-policy layer (KLC-045)" section with gate levels table,
  signals table, and `klc ack --auto` usage.

## Outcome

pass
