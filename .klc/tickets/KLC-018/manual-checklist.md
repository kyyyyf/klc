---
ticket: KLC-018
phase: manual
authority: agent
---

# KLC-018 manual checklist

## Pre-merge checks

- [x] `klc doctor` → DOCTOR_OK
- [x] `python3 tests/smoke.py` → OK
- [x] `python3 tests/e2e_pipeline.py` → ALL 4 tracks + negative + conditional PASSED
- [x] `python3 tests/integration/test_review_cascade.py` → 6 tests PASSED
- [x] `python3 tests/integration/test_token_telemetry.py` → 6 tests PASSED

## AC spot-checks

- [x] AC-A1: XS track uses `discovery-lite` (verified via e2e phase list)
- [x] AC-A2: `route_heuristic.classify("fix typo", bug)` → XS ✓
- [x] AC-A3: force-xs-skip blocked for non-XS route_hint (guard in ack.py)
- [x] AC-B2: empty file_tiers → full review (test_empty_file_tiers_forces_full_review)
- [x] AC-C1: envelope split present in runner.py
- [x] AC-D1: unknown_files bucket in scope_delta.compare()
- [x] AC-D2: modules.json absent for review → hard fail
- [x] AC-E1: validate_condition_syntax() added and called in validate_all()

## Known gaps (non-blocking, flagged in review)

- [ ] Double import of `phases` in validate_condition_syntax (MEDIUM, cosmetic)
- [ ] `ticket_key` detection hardcoded to "KLC-" prefix (LOW)
- [ ] Missing integration tests for AC-A3, AC-D1, AC-E1 (LOW)
