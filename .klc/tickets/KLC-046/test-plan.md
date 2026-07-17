---
ticket: KLC-046
kind: test-plan
authority: human
last_generated: 2026-06-24
---

# KLC-046 — Test plan

## Acceptance coverage

| AC | Test | Kind | Asserts |
| AC-1 | `test_run_dispatches_work_state` | integration | At a `:work` state the loop calls the injected dispatch (build → orchestrator path, others → run_agent with `track=`), then re-reads state. |
| AC-2 | `test_run_auto_acks_clean_conditional` | integration | At `:ack-needed` with a clean conditional gate, the loop invokes the real `ack --auto` and `lifecycle.current_state` advances; a dirty signal pauses with a notification naming the reason and phase unchanged. |
| AC-3 | `test_run_pauses_on_decision_gate` | integration | A decision gate pauses with a notification even when signals are clean; `meta.json:phase` unchanged. |
| AC-4 | `test_guardrail_*` (integrate, budget ceiling, cap) | integration | The loop pauses on each guardrail; each pause names which guardrail fired. Outward classification is phase-id based (`integrate`), NOT a pick goto/label heuristic (audit fix #4 — the merge-pick test is removed). |
| AC-5a | `test_run_ml_design_decision_simulation` | integration | Real M/L fixture at `design:work`: the loop dispatches (faked), auto-detects completion, reaches `design:ack-needed`, and HALTS there because the design picks are all `decision` gates; `paused_at == "design"`, reason names the decision gate. |
| AC-5b | `test_run_clean_s_ticket_simulation` | integration | Real S fixture at `build:work`: `meta.json:phase` ACTUALLY walks build→review (asserted per state) with only agent dispatch faked, then HALTS at the integrate guardrail (`paused_at == "integrate"`). A trace-only loop fails this. (S has no design phase — that is why AC-5a needs an M/L fixture.) |
| AC-6 | `test_run_writes_run_log` | integration | The run log records each transition, gate evaluation, and pause reason with the caller-supplied timestamp. |
| AC-7 | `test_run_refuses_feature_on` + `test_run_rc_disambiguation` | integration | With `state_feature.enabled()` True the loop refuses and takes no transition. Feature-off, `ack --auto` rc 0 = advanced, rc 2 = gate pause, any other non-zero rc = an error pause with its own message. |

## Edge cases (each a NAMED test, not prose)

- `test_run_dispatch_failure_pauses`: a dispatched agent returns non-zero → the loop pauses at
  that `:work` (does not advance past a failed phase) and logs it.
- `test_run_cap_mid_run`: the consecutive-auto cap is reached mid-run → pause with the cap
  guardrail even though the next gate is clean.
- `test_run_already_at_decision`: a ticket already at a decision gate when `klc run` starts →
  immediate pause, no dispatch, no transition.
- `test_run_failclosed_signal_pauses`: an unavailable signal (no modules.json) → gate_policy
  dirty → pause, not proceed.
- `test_dispatch_uses_rendered_card_not_generic_prompt` (P1-A): a non-build phase is
  dispatched with the rendered `.klc/tickets/<KEY>/<phase>/_prompt.md`, NOT
  `core/agents/<phase>.md`; the card exists on disk with the concrete key.
- `test_missing_declared_output_fails_closed` (P1-B, via the gate): a dispatch that returns 0
  but does not write the required artifact → `ack --auto` rc 1 → the loop pauses fail-closed
  with the gate's CAUSAL reason ("Missing review-report.md") in the reason AND the run-log —
  not the trailing abort hint (FIX-2). State unchanged. (The fake must NOT write the outputs.)
- `test_xs_discovery_lite_not_wrongly_paused` (FIX-1): an XS discovery-lite dispatch producing
  only `spec.md` (all the XS gate requires) must NOT be blocked for a "missing"
  test-plan.md/impl-plan.md (phases.yml superset). The loop reaches discovery-lite:ack-needed
  and pauses at the DECISION gate — proving the runner does not duplicate per-track output
  rules.
- `test_run_badkey_rc1_no_dir` / `test_run_badkey_no_traceback` (P2): `klc run <BADKEY>` →
  rc 1, friendly, and NO `.klc/tickets/<BADKEY>/` dir created; no traceback.
- `test_corrupt_meta_logged_pause`: a corrupt `meta.json` mid-run → a LOGGED fail-closed
  pause, not a traceback.
- `test_refusal_feature_on_is_logged`: the feature-on refusal is recorded in the run log.
- `test_ack_error_reason_includes_detail`: a non-2 non-0 ack rc surfaces ack's stderr detail
  into the pause reason (not a bare `ack --auto error (rc=N)`).

## Regression scenarios

- `test_run_never_merges_or_pushes` (SAFETY INVARIANT): drive the full simulation with the
  fake dispatch/subprocess recording every command; assert ZERO `git merge` / `git push`
  invocations and that `paused_at == "integrate"`. This is the single most safety-critical
  guarantee and must be an explicit assertion.
- Manual `klc ack` / `klc next` behaviour is unchanged by the presence of the runner.

## Detailed coverage

(Filled by the detailed-test-plan phase: per-step unit/integration test names mapped to the
impl-plan steps below. Each impl-plan step's RED names its tests; this table cross-links them.)
