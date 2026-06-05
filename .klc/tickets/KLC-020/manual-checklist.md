---
ticket: KLC-020
phase: manual
authority: agent
---
# KLC-020 manual checklist

- [x] `klc doctor` → DOCTOR_OK
- [x] `python3 tests/smoke.py` → OK
- [x] `python3 tests/e2e_pipeline.py` → all 4 tracks + negative + conditional PASSED
- [x] `python3 tests/integration/test_jira_core.py` → 12/12 PASSED
- [x] `klc jira status` exits non-zero when disabled
- [x] `_flatten_adf` duplication fixed (MEDIUM from review)
- [x] `docs/process.md` Jira section added
