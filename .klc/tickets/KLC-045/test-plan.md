---
ticket: KLC-045
kind: test-plan
authority: human
last_generated: 2026-06-24
---

# KLC-045 — Test plan

## Acceptance coverage

| AC | Test | Kind | Asserts |
| AC-1 | `test_pick_gate_field_parsed` | unit | A pick with `gate: conditional` parses to `Pick.gate == "conditional"`; a missing `gate` defaults to `decision`; an unknown value raises at load. |
| AC-2 | `test_every_pick_has_gate` | unit | Loading `config/phases.yml`, every pick across every phase has an explicit `gate`; the four decision gates (discovery/discovery-lite approve, design pick, manual passed, integrate merged) are `decision`. |
| AC-3 | `test_evaluate_auto_conditional_decision` + `test_evaluate_missing_signal_is_dirty` | unit | auto→proceed; decision→pause; conditional all-clean→proceed; conditional any-dirty→pause; a signals dict MISSING the `verdict` or `route_confidence` key → pause (fail-closed), not proceed. |
| AC-4 | `test_collect_signals_clean` + `test_collect_signals_dirty` | integration | Clean fixture → all seven keys (advisory, scope_expansion, sentinels, mutation, budget_overrun, verdict, route_confidence) clean. Dirty fixture (planted scope expansion + sentinel hit in diff + budget counter at limit) → those VALUES come back dirty (not just key presence). |
| AC-5 | `test_ack_auto_proceeds_clean` / `test_ack_auto_refuses_risky` / `test_ack_no_auto_unchanged` | integration | Drives the real `ack.run([KEY,"--auto"])`: clean conditional auto-acks AND `lifecycle.current_state` advanced; risk flag → non-zero, reasons named, phase UNCHANGED; plain `ack.run([KEY])` behaves exactly as before (no policy consulted). |
| AC-6 | `test_decision_never_auto` + `test_ack_auto_refuses_low_route_confidence` | integration | A decision pick with clean signals → pause, phase unchanged; `route_confidence=="low"` forces pause on a conditional pick (route_confidence risk path, distinct from scope). |

## Edge cases

- Missing signal source (no modules.json for scope_delta; no git/diff for sentinels; no
  review-report.md for verdict): `collect_signals` must yield a DIRTY value and `evaluate`
  must pause (fail-closed). Covered by `test_collect_signals_dirty` + `test_evaluate_missing_signal_is_dirty`.
- A `pick_required` multi-pick phase (e.g. review: approve / request-changes): `--auto` must
  resolve the forward (`goto: next`) pick and pass its id to `apply_ack` (which RAISES on a
  None pick_id). Covered by `test_ack_auto_proceeds_clean` on such a phase.
- `--auto` on a `:work` state (not yet `:ack-needed`): behaves like plain ack (runs completion
  detection first), then applies policy at `:ack-needed`.
- An unknown `gate` value in a hand-edited `phases.yml` must fail loudly at load
  (`test_pick_gate_field_parsed`), not be silently treated as `decision`.

## Regression scenarios

- Plain `klc ack` (no `--auto`) on every phase produces byte-for-byte the same prompts and
  transitions as before this ticket (`test_ack_no_auto_unchanged`).
- Adding `gate` to picks does not change `klc status` / `klc board` output shape.
