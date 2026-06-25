---
ticket: KLC-051
authority: hybrid
---

# Manual checklist — KLC-051

## Acceptance checks

- [x] AC-1: `plan_quality.unresolved_api_refs` correctly flags `scan_sentinels.scan(` and passes `scan_sentinels.scan_diff(` — verified by `test_unresolved_api_refs_flags_missing` + `test_unresolved_api_refs_ignores_unknown_and_self`.
- [x] AC-2: Discovery-lite ack is blocked when impl-plan has unresolved API ref — verified by `test_plan_quality_gate_blocks_bad_ref` + M/L path by `test_plan_quality_gate_blocks_bad_ref_on_design_ack`.
- [x] AC-3: All three planning prompts carry "public entry point" rule — verified by `grep -rln "public entry point" core/agents/design.md core/agents/discovery-lite.md core/agents/test-planner.md`.
- [x] AC-4: `test_planning_prompts_endtoend_rule` is permanent, not `xfail`.
- [x] AC-5: `design.md` and `discovery-lite.md` both contain `plan_quality.unresolved_api_refs` directive — verified by `test_planning_prompts_api_check_directive`.
- [x] AC-6: `grep -n "completeness-audit" docs/process.md` returns the adversarial audit section.

## Outcome

**pass**
