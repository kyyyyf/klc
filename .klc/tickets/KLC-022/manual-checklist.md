---
ticket: KLC-022
phase: manual
authority: agent
---
# KLC-022 manual checklist (rework pass)

- [x] `klc doctor` → DOCTOR_OK
- [x] `python3 tests/smoke.py` → OK
- [x] `python3 tests/e2e_pipeline.py` → all 4 tracks + negative + conditional PASSED
- [x] `python3 tests/integration/test_jira_pull.py` → 12/12 PASSED
- [x] All 7 blocking findings from codex_review resolved
- [x] supersede range corrected (target not superseded)
- [x] backward non-TTY aborts; backward TTY requires confirmation
- [x] jira-pull/force-pull events suppress push hook
- [x] conditional skips write structured event=skipped to phase_history
- [x] force-pull --reason required
- [x] docs pull/force-pull semantics section added
