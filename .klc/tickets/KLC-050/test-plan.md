---
ticket: KLC-050
kind: test-plan
authority: human
---

# KLC-050 — Test plan

## Acceptance coverage

| AC | Test | Kind | Asserts |
| AC-1 | `test_lint_catches_paraphrases` / `test_lint_ignores_benign` | unit | `lint_text` flags "don't flag this", "ignore this issue", "treat as minor", "downgrade it"; does not flag benign review prose. |
| AC-2 | `test_recorded_pick_rejects_placeholder` + `test_recorded_pick_accepts_concrete` | unit | False for empty / `Picked: <approach>` / `Picked: TBD`; True for `Picked: Option A — reason` (incl. trailing whitespace — guards the `\s*$` false-positive) and for a `DECISION D-001`-only spec. |
| AC-3 | `test_model_guard_strict_rejects` + `test_runner_refuses_dispatch_without_model` + `test_build_orchestrator_refuses_dispatch_without_model` | unit/integration | The helper raises on no model; AND at BOTH real dispatch call sites (runner ~318, build_orchestrator ~144), an unresolved model raises/returns non-zero with the mocked dispatch invoked ZERO times (wiring proof, not helper-only). |
| AC-4 | `test_single_step_parser` | unit | The ADAPTED `phase_completion._impl_plan_steps` still yields `{step:int, red_not_applicable}` (what its line-466 consumer needs) while delegating to the single `parse_impl_plan_steps`; the duplicate regex is gone. |
| AC-5 | `test_plan_template_renders_gate_passing` | unit | Any shipped `impl-plan*.j2` renders a skeleton that `impl_plan_violations` accepts (or the templates are absent). |

## Edge cases

- The broadened lint must not over-match legitimate prose like "the reviewer should not
  ignore edge cases" — negative fixtures guard against false positives.
- `recorded_pick` must still accept `DECISION D-001` style picks (the existing alternate
  marker), not only `Picked:`.
- The strict model-guard path must remain opt-in enough that existing tests with a resolved
  model are unaffected.

## Regression scenarios

- The KLC-031/032 tests still pass with the broadened lint / hardened pick (no regression to
  previously-valid inputs).
- Removing a stale template does not break any live render path (grep confirms no caller).
