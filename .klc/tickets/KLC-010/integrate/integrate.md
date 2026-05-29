---
ticket: KLC-010
phase: integrate
completed_at: 2026-05-29T15:00:00Z
---

# Integration Report — KLC-010

## Pre-merge checklist

- [x] Branch: `feature/KLC-010-layered-deps`
- [x] Commits: 10 commits (9 feature + 1 test fix)
- [x] All tests pass:
  - [x] 64 unit/integration tests (36 unit + 28 integration)
  - [x] smoke.py: OK
  - [x] e2e_pipeline.py: ALL TESTS PASSED (4 tracks)
- [x] Code review: APPROVED (4 blocking issues fixed)
- [x] Manual testing: PASSED (all 9 ACs verified)

## Commits included

```
4831f9c fix(tests): align e2e_pipeline.py with phases.yml design outputs
1b7d7e0 fix(KLC-010): resolve 4 blocking review issues (ARCH-1, PERF-1, TEST-1, TEST-2)
74f3795 fix(KLC-010): remove backup file from commit
9acc437 feat(KLC-010): step-7 - update init output and README install instructions
83181b0 feat(KLC-010): step-6 - extend klc doctor with project-tool validation
2ef5c0b feat(KLC-010): step-5 - implement detect_languages and klc setup
eff7abe feat(KLC-010): step-4 - implement project module and refactor dispatcher
fd3d769 feat(KLC-010): step-3 - implement dev module
3cb6633 feat(KLC-010): step-2 - implement bootstrap module
d757c12 feat(KLC-010): step-1 - create core/deps package structure
```

## Files changed

**Created** (17 files):
- `core/deps/__init__.py` (114 lines)
- `core/deps/bootstrap.py` (76 lines)
- `core/deps/dev.py` (67 lines)
- `core/deps/project.py` (276 lines)
- `core/skills/detect_languages.py` (112 lines)
- `core/phases/setup.py` (174 lines)
- `tests/deps/test_utils.py` (133 lines)
- `tests/deps/test_bootstrap.py` (113 lines)
- `tests/deps/test_dev.py` (119 lines)
- `tests/test_install_deps.py` (54 lines)
- `tests/test_detect_languages_threshold.py` (114 lines)
- `tests/test_detect_languages_malformed.py` (161 lines)
- `tests/integration/test_setup_integration.py` (221 lines)
- `tests/integration/test_doctor_integration.py` (239 lines)
- `tests/integration/test_init_integration.py` (108 lines)

**Modified** (4 files):
- `scripts/install_deps.py` (342 → 67 LOC, -81% refactored to dispatcher)
- `core/phases/doctor.py` (+55 lines, new project-tools check)
- `scripts/init.py` (+7 lines, setup hint)
- `scripts/klc` (+1 line, register setup command)
- `README.md` (+50 lines, updated install flow)
- `tests/e2e_pipeline.py` (+6/-2, fix design phase expectations)

**Total impact**: +2421/-329 lines across 22 files

## Post-merge actions

- [ ] Merge to main (ready, awaiting PR creation/approval)
- [ ] Record merge commit SHA in meta.json
- [ ] Verify CI green on main
- [ ] Close Jira ticket (if exists)

## Integration notes

**Backward compatibility**: Preserved
- `install_deps.py` without flags still works (calls project mode by default)
- Existing `.klc/` directories unaffected
- No breaking changes to public APIs

**Migration path**: None required
- New `.klc/index/project-deps.json` auto-generated on first `klc setup` run
- Existing projects continue working without changes

**Dependencies**: None new
- All new modules use stdlib + existing framework dependencies
- PyYAML soft dependency (graceful degradation if missing)

## Ready for merge

All acceptance criteria met, all tests pass, code review approved, manual testing complete.

**Next**: Create PR, merge to main, update meta.json with merge SHA.
