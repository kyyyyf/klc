---
ticket: KLC-008
authority: agent
---

# Test Plan: E2E test infrastructure

## Test scenarios

### TS-1: XS-track lifecycle (happy path)
**Priority**: P0  
**Preconditions**: Clean checkout, `PROJECT_ROOT` set  
**Steps**:
1. Run `python tests/e2e_pipeline.py --track XS`
2. Verify ticket transitions: intake → xs-build → review-lite → integrate → learn → archived
3. Verify artefacts: raw.md, build-log.md, review-report.md, integrate.md, retrospective.md

**Expected**: All phases complete, exit 0, <15s runtime

---

### TS-2: S-track lifecycle (happy path)
**Priority**: P0  
**Preconditions**: Clean checkout, `PROJECT_ROOT` set  
**Steps**:
1. Run `python tests/e2e_pipeline.py --track S`
2. Verify ticket transitions: intake → discovery → acceptance-test-plan → build → review → integrate → observe → learn → archived
3. Verify artefacts: raw.md, spec.md, test-plan.md, impl-plan.md, build-log.md, review-report.md, integrate.md, observe.md, retrospective.md

**Expected**: All phases complete, exit 0, <20s runtime

---

### TS-3: M-track lifecycle (happy path)
**Priority**: P0  
**Preconditions**: Clean checkout, `PROJECT_ROOT` set  
**Steps**:
1. Run `python tests/e2e_pipeline.py --track M`
2. Verify additional phases vs S-track: design, detailed-test-plan
3. Verify artefacts: design.md added

**Expected**: All M-track phases complete, exit 0, <25s runtime

---

### TS-4: L-track lifecycle (happy path)
**Priority**: P0  
**Preconditions**: Clean checkout, `PROJECT_ROOT` set  
**Steps**:
1. Run `python tests/e2e_pipeline.py --track L`
2. Verify additional phase vs M-track: manual
3. Verify manual phase artefacts

**Expected**: All L-track phases complete, exit 0, <30s runtime

---

### TS-5: Ack pick validation
**Priority**: P0  
**Preconditions**: Ticket in `discovery:ack-needed`  
**Steps**:
1. Call `klc ack <ticket>` without `--pick` for phase requiring pick
2. Verify error message names required picks

**Expected**: Exit 1, error: "pick required for discovery phase"

---

### TS-6: Invalid transition rejection
**Priority**: P1  
**Preconditions**: Ticket in `discovery:work`  
**Steps**:
1. Attempt `klc jump build <ticket>` (skip acceptance-test-plan)
2. Verify error: missing inputs

**Expected**: Exit 1, error names missing artefacts (test-plan.md)

---

### TS-7: Missing artefact detection
**Priority**: P0  
**Preconditions**: Ticket in `discovery:work`, no spec.md  
**Steps**:
1. Run `klc ack <ticket> --pick 1`
2. Verify error names missing artefact

**Expected**: Exit 1, error: "Missing spec.md"

---

### TS-8: Temp directory cleanup
**Priority**: P1  
**Preconditions**: e2e test fails mid-run  
**Steps**:
1. Inject failure in phase 3 (acceptance-test-plan)
2. Verify teardown runs in `finally` block
3. Check no temp dirs remain in `/tmp`

**Expected**: No leaked temp directories

---

### TS-9: Fixture format validation
**Priority**: P1  
**Preconditions**: All fixtures in `tests/fixtures/fake-agent-outputs/`  
**Steps**:
1. For each fixture, verify frontmatter matches `process-artifacts.md` schema
2. Check required sections present (## Goals, ## Acceptance Criteria, etc.)

**Expected**: All fixtures valid per schema

---

### TS-10: Phase completion unit tests
**Priority**: P0  
**Preconditions**: `tests/test_phase_completion.py` exists  
**Steps**:
1. Run `pytest tests/test_phase_completion.py -v`
2. Verify coverage: every phase in `config/phases.yml` has test

**Expected**: All tests pass, 100% phase coverage

---

### TS-11: Lifecycle state machine unit tests
**Priority**: P0  
**Preconditions**: `tests/test_lifecycle.py` exists  
**Steps**:
1. Run `pytest tests/test_lifecycle.py -v`
2. Verify tests cover: legal transitions, illegal jumps, track filtering

**Expected**: All tests pass

---

### TS-12: Runtime budget
**Priority**: P1  
**Preconditions**: All 4 track tests enabled  
**Steps**:
1. Run `time python tests/e2e_pipeline.py`
2. Measure total runtime

**Expected**: <60s for all tracks combined

---

## Automation

- **CI integration**: Add `make test-e2e` target that runs `e2e_pipeline.py` after `smoke.py`
- **Pre-commit hook**: Optional — run on refactor PRs only (KLC-007, KLC-009)

## Acceptance coverage

| AC | Test scenarios |
|----|---------------|
| AC-1: Exit 0 on clean checkout | TS-1, TS-2, TS-3, TS-4 |
| AC-2: All 4 tracks tested | TS-1 (XS), TS-2 (S), TS-3 (M), TS-4 (L) |
| AC-3: Artefacts match phases.yml | TS-1, TS-2, TS-3, TS-4, TS-9 |
| AC-4: Runtime <60s | TS-12 |
| AC-5: Temp dir cleanup | TS-8 |
| AC-6: Failure messages clear | TS-5, TS-7 |
| AC-7: test_phase_completion.py coverage | TS-10 |
| AC-8: test_lifecycle.py validates state machine | TS-11 |

## Coverage

| Component | Coverage target | Method |
|-----------|----------------|--------|
| Phase transitions | 100% | e2e_pipeline.py parametrized over tracks |
| Artefact validation | 100% of outputs in phases.yml | Assertion per phase |
| Ack picks | 100% of pick_required phases | test_phase_completion.py |
| State machine | All legal + sample illegal | test_lifecycle.py |

## Edge cases

- **EC-1**: Ticket with incomplete meta.json (missing track) → should error in intake validation
- **EC-2**: Phase with no outputs declared in phases.yml → skip artefact check
- **EC-3**: Fixture file missing for a phase → test should fail with clear message
- **EC-4**: `PROJECT_ROOT` not set → error at startup, not mid-run
- **EC-5**: Multiple concurrent e2e runs → temp dirs don't collide (use ticket key in path)
- **EC-6**: phases.yml modified to add new phase → test discovers it via dynamic loading

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Fake fixtures drift from real outputs | Medium | Pin to schema in process-artifacts.md |
| Tests too slow | Low | Profile, optimize fixture I/O |
| Temp dir leaks in CI | Low | Always use `try/finally` cleanup |

## Test data

- **Fake ticket**: `TEST-001`, kind=feature, trivial description
- **Config stubs**: Minimal `phases.yml` (only tested tracks), `models.yml` (dummy model refs), `profile.yml` (generic)
- **Fixtures**: One per phase output, ~50-100 lines each
