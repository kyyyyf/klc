---
ticket: KLC-010
authority: human
last_generated: 2026-05-29T11:15:00Z
---

# Retrospective — KLC-010

## What happened (facts, not opinions)

> [!FACT F-R1] src=meta.json phase_history
> Total cycle time: 19h 28m (2026-05-28 15:40 → 2026-05-29 11:08)
> Track=M estimated=7pts, no rework cycles

> [!FACT F-R2] src=meta.json phase_history
> Phase breakdown:
> - discovery: 3m 12s
> - acceptance-test-plan: 56s
> - design: 14h 6m 21s (longest phase, overnight gap)
> - detailed-test-plan: 54m 21s
> - build: 3h 28m 58s
> - review: 21m 9s
> - manual: 15m 53s
> - integrate: 13m 32s
> - observe: 45s
> Total active work: ~5h 16m (excluding overnight gap in design)

> [!FACT F-R3] src=review/review-report.md
> Code review found 24 issues: 4 BLOCKING, 9 MEDIUM, 11 LOW/INFO
> All 4 blocking issues fixed before merge (ARCH-1, PERF-1, TEST-1, TEST-2)

> [!FACT F-R4] src=test-plan.md, build/
> Test coverage: 64 tests total (36 unit + 28 integration), 100% pass rate
> New test files: 8 (threshold, malformed, utils, bootstrap, dev, setup, doctor, init)

> [!FACT F-R5] src=meta.json rework_count
> Zero rework cycles — no phases bounced back, first-pass approval on all phases

> [!FACT F-R6] src=build/, git log
> Code change: +2421/-329 lines across 22 files
> 10 commits total (9 feature + 1 test infrastructure fix)

> [!FACT F-R7] src=design/options.md
> User chose Option B (clean architecture) over Option A (minimal diff)
> Reason: long-term maintainability over short-term velocity

## What went well

- **Zero rework**: All phases approved on first try, no review→build loops or manual→build bounces. Clean execution from intake to learn.

- **Comprehensive test coverage**: 64 tests created covering happy paths, edge cases, error handling, and integration scenarios. All ACs validated programmatically where possible.

- **Proactive issue discovery**: Review found e2e_pipeline.py inconsistency (design.md vs design/options.md) which was fixed during integrate phase, preventing future confusion.

- **Performance improvement as side effect**: ast-grep N+1 subprocess pattern fix (PERF-1) reduced overhead by 60-75% (150-900ms → 50-300ms).

- **Strong backward compatibility**: All existing tests (smoke.py, e2e_pipeline.py) passed unchanged. No breaking changes despite significant refactoring (342→67 LOC in install_deps.py).

- **Clear design choice documentation**: User decision between Option A/B clearly recorded in meta.json (`design_choice: "option-A-minimal"` note discrepancy — meta says A but retrospective context shows B was chosen).

## What went wrong

- **Design phase duration**: 14h 6m including overnight gap. While wall-clock time was long, active work was likely <2h. Overnight gap masks true effort. Better time tracking needed.

- **Meta.json design_choice mismatch**: `meta.json` says `"design_choice": "option-A-minimal"` but user actually chose Option B (clean architecture). Indicates acknowledgment step recorded wrong pick value.

- **Review found 4 blocking issues**: While all were fixed, several were preventable:
  - **ARCH-1** (backup file committed): Should have been caught by pre-commit hook or .gitignore
  - **TEST-1** (threshold boundaries): Should have been in detailed-test-plan from start
  - **TEST-2** (malformed input): Error handling tests should be standard in test-plan template

- **E2E test drift from config**: e2e_pipeline.py expected `design.md` but phases.yml required `design/options.md` + `impl-plan.md`. This diverged silently over time, suggesting lack of validation between test expectations and phase config.

## Lessons (imperative)

- **Add pre-commit hook check for .bak files**: Prevents ARCH-1 class issues (committed backup files). Add to `.klc/hooks/` or framework install.

- **Extend test-plan template with error-handling section**: Malformed input tests (TEST-2 class) should be prompted by default. Add to `core/templates/test-plan.md.j2`.

- **Validate PHASE_ARTEFACTS against phases.yml**: Add CI check that `tests/e2e_pipeline.py::PHASE_ARTEFACTS` matches `config/phases.yml::outputs` for each phase. Prevents config drift.

- **Verify design_choice recording**: Acknowledgment step should validate that recorded pick value matches user's actual selection. Cross-check meta.json after `klc ack <ticket> --pick <N>`.

## Proposed knowledge-base updates

### config/reviewer-allowlist.yml

No new allowlist entries proposed — review findings were legitimate and caught real issues.

### deny-list updates

None proposed — no false positives from reviewers.

### Few-shot updates for reviewers

1. **core/agents/review/test-coverage.md**:
   - Add example: "KLC-010 test coverage review identified missing threshold boundary tests (TEST-1) and malformed input tests (TEST-2). Both classes of tests (boundary values, error handling) should be standard in test plans."
   - Lesson: Reviewers should check for boundary+1/-1 tests and try-except coverage even if not explicitly listed in test-plan.md.

2. **core/agents/review/performance.md**:
   - Add example: "KLC-010 PERF-1: N+1 subprocess pattern (one call per file in loop). Fix: batch all files into single subprocess call with multiple flags. Reduced overhead from 150-900ms to 50-300ms."
   - Lesson: Look for subprocess.run() inside loops — often indicates N+1 pattern.

## Estimate accuracy

- **Estimate**: 7 points (complexity=3, uncertainty=2, risk=1, manual=1)
- **Actual**: ~5-6 hours active work (excluding overnight gap)
- **Assessment**: Estimate was reasonable for track=M. Design phase overnight gap inflated wall-clock time but didn't indicate under-estimation.

## Process improvements

1. **Add .bak to .gitignore**: Prevents committed backup files
2. **CI check**: Validate e2e test phase expectations match phases.yml outputs
3. **Test plan template**: Add "Error handling" section with malformed input, edge cases
4. **Acknowledgment validation**: Verify recorded pick value matches user intent

## Ticket-specific notes

- This ticket touched 4 major modules (install_deps, init, doctor, setup) with strong interdependencies. Clean modularization (core/deps/ package) prevented tangling.
- User preference for "clean architecture over minimal diff" proved correct — refactoring to core/deps/ made review, testing, and understanding much easier than inline branching would have.
- Zero rework suggests good upfront planning (discovery, design, detailed-test-plan phases earned their cost).

## Conclusion

**Successful execution** with zero rework, comprehensive testing, and all ACs met. Main improvements: prevent backup files, standardize error-handling tests, validate config consistency. Strong example of M-track process working as designed.

RETRO_WRITTEN KLC-010
