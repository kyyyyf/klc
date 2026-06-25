---
ticket: KLC-051
kind: test-plan
authority: human
last_generated: 2026-06-25
---

# KLC-051 — Test plan

## Acceptance coverage

| AC | Test | Kind | Asserts |
| AC-1 | `test_unresolved_api_refs_flags_missing` / `test_unresolved_api_refs_ignores_unknown_and_self` | unit | A sketch calling `scan_sentinels.scan(` is flagged; `scan_sentinels.scan_diff(` is not; `os.path.join(` and `re.compile(` (non-skill modules) are ignored; a reference to a symbol introduced by the same plan is not flagged. |
| AC-2 | `test_plan_quality_gate_blocks_bad_ref` (integration, through `can_complete`) | integration | An impl-plan fixture referencing `scan_sentinels.scan(` makes `can_complete_discovery_lite` / design ack return blocked naming the unresolved ref; the same plan with `scan_diff(` passes. Driven through the real `can_complete_*` entry, not `unresolved_api_refs` directly. |
| AC-3 | `test_planning_prompts_carry_test_rule` | unit | `design.md`, `discovery-lite.md`, `test-planner.md` each contain the end-to-end + negative-test rule text. |
| AC-4 | `test_planning_prompts_endtoend_rule` (KLC-029 harness) | prompt-regression | The harness asserts the rule is present in all three prompts (permanent regression guard, not `xfail`). |
| AC-5 | `test_self_review_runs_api_check` | unit | The self-review path invokes `unresolved_api_refs` and surfaces an unresolved ref (mirrors KLC-037's self-scan shape). |
| AC-6 | `test_docs_document_plan_quality` | unit | `grep` confirms `docs/process.md` documents the plan-quality gate and the adversarial completeness-audit prep step. |

## Edge cases

- A code sketch references a method via an aliased import (`ack_cmd.run`): the conservative
  matcher does NOT flag it (alias unresolved) — verified so the gate stays low-false-positive,
  documented as a known limitation.
- A reference to a dunder or private attr (`budget._load_limits(`): resolves against the module
  like any other attr (private is fine — the module defines it).
- A module name that collides with a stdlib name (e.g. a hypothetical `core/skills/json.py`):
  the matcher resolves against the core/skills file, not stdlib — assert it reads the project module.
- An impl-plan with no code sketches (all steps `RED: not applicable`): `unresolved_api_refs`
  returns `[]`, the gate is a no-op.

## Regression scenarios

- Every already-prepared ticket's impl-plan (045/046/047/049/050/051) passes
  `unresolved_api_refs` after this lands — i.e. the new gate does not retroactively block the
  in-flight plans (run it over them as a regression fixture; fix any real unresolved ref found).
- The KLC-036 plan-completeness gate behaviour is unchanged for plans with resolvable APIs.
