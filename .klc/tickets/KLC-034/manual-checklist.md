---
ticket: KLC-034
authority: hybrid
---

# Manual checklist — KLC-034

## Acceptance checks

- [x] AC-1: Both `discovery.md` and `discovery-lite.md` contain `AskUserQuestion` directive; "one question at a time" and "2-3 approaches" markers are preserved — verified by `grep -n AskUserQuestion core/agents/discovery*.md` and `test_discovery_prompts_have_socratic_step`.
- [x] AC-2: `core/skills/spec_structure.py` gains `has_upgrade_m_signal` at line 51 using module-level `_UPGRADE_M_RE` — no duplicated regex; `test_upgrade_m_signal_helper` passes.
- [x] AC-3: `can_complete_discovery_lite` surfaces `(True, "DISCOVERY_LITE_UPGRADE_M: scope exceeds S — re-route via 'klc retrack <KEY> M'")` when signal is present — non-blocking; `test_upgrade_m_signal_recognized` passes.
- [x] AC-4: `test_discovery_prompts_use_askuserquestion` in `tests/test_prompt_regression.py` is permanent (no xfail); confirmed RED on pre-step-2 commits.
- [x] AC-5: `test_one_question_at_a_time_judge_fixture` skips without API key (CI-safe); fixture at `tests/fixtures/klc-034-socratic-input.md`.
- [x] AC-6: `docs/process.md` — "Discovery Socratic protocol (KLC-034)" section with AskUserQuestion + UPGRADE_M live signal table; `docs/roles.md` — discovery role updated; `docs/process-artifacts.md` — options-lite.md section + re-route signals table.

## Outcome

**pass**
