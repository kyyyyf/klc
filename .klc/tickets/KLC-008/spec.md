---
ticket: KLC-008
kind: tech
authority: agent
classification:
  complexity: 2
  uncertainty: 2
  risk: 0
  manual: 1
  total: 5
track: S
estimate_days: 5
layer: test-infrastructure
affected_modules:
  - tests
---

# KLC-008 — E2E test infrastructure: fake-agent pipeline

## Goals

Build a regression-proof harness that runs a ticket through the complete lifecycle using deterministic fake agents, verifying state transitions and artefact generation at each phase.

## Problem

Current test coverage:
- `tests/smoke.py` (517 lines) tests pipeline machinery but doesn't run full lifecycle
- `tests/test_callgraph_rust_lsp.py` tests one skill in isolation

**Gap**: No test verifies that a ticket can traverse intake → discovery → design → build → review → integrate → observe → learn → archived with correct:
- State transitions per `config/phases.yml`
- Artefact generation per phase outputs
- Ack pick validation
- Track-specific phase inclusion/exclusion

This means refactors (KLC-007) and config changes (KLC-009) can silently break the lifecycle.

## Solution

### Core components

1. **`tests/e2e_pipeline.py`** — main harness
   - Creates isolated temp `.klc/` root with minimal config
   - Seeds fake ticket with `raw.md`
   - Drives ticket through phases using fake agents
   - Verifies state transitions and artefacts
   - Parametrized over tracks (XS/S/M/L)
   - Runtime target: <60s total

2. **`tests/fixtures/fake-agent-outputs/<phase>.md`** — canned artefacts
   - `discovery.md` → `spec.md`
   - `acceptance-test-plan.md` → `test-plan.md`
   - `design.md` → `design.md`
   - `detailed-test-plan.md` → `test-plan.md` (extended)
   - `build.md` → `build-log.md`
   - `review.md` → `review-report.md`
   - `integrate.md` → `integrate.md`
   - `observe.md` → `observe.md`
   - `retrospective.md` → `retrospective.md`

3. **Fake agent pattern**
   - Not an LLM mock
   - Simple file writer: `cat fixture → artefact path`
   - No model behavior simulation
   - Deterministic: same input → same output

4. **`tests/test_phase_completion.py`** — unit tests
   - Covers every phase's completion check
   - Verifies required artefacts detection
   - Tests ack pick validation

5. **`tests/test_lifecycle.py`** — state machine unit tests
   - Validates legal transitions per `phases.yml`
   - Rejects invalid jumps
   - Tests track filtering

### Track variants

| Track | Phases covered | Fixture count |
|-------|----------------|---------------|
| XS    | intake → xs-build → review-lite → integrate → learn | 4 |
| S     | intake → discovery → acceptance-test-plan → build → review → integrate → observe → learn | 7 |
| M     | S + design + detailed-test-plan | 9 |
| L     | M + manual | 10 |

### Implementation approach

```python
# Pseudocode structure
class E2EPipeline:
    def setup(self):
        # Create temp .klc/ with minimal config
        # Copy phases.yml, models.yml, profile stub
        
    def seed_ticket(self, track):
        # Write raw.md
        # Run `klc intake`
        
    def run_phase(self, phase_id):
        # Copy fixture → artefact
        # Run `klc ack --pick 1`
        # Assert phase advanced
        # Assert artefacts exist
        
    def teardown(self):
        # rm -rf temp dir
        
    @pytest.mark.parametrize("track", ["XS", "S", "M", "L"])
    def test_full_lifecycle(self, track):
        self.setup()
        self.seed_ticket(track)
        for phase in phases_for_track(track):
            self.run_phase(phase)
        assert final_state == "archived"
        self.teardown()
```

## Acceptance Criteria

- **AC-1**: `python tests/e2e_pipeline.py` exits 0 on clean checkout
- **AC-2**: All 4 tracks (XS/S/M/L) tested; each completes without error
- **AC-3**: For each phase, harness verifies artefacts match `config/phases.yml` outputs
- **AC-4**: Total runtime <60s on developer machine
- **AC-5**: Harness leaves no residue (temp dir cleaned in `finally`)
- **AC-6**: Failure messages name: phase, ticket key, missing/extra artefact
- **AC-7**: `tests/test_phase_completion.py` covers every phase in `config/phases.yml`
- **AC-8**: `tests/test_lifecycle.py` validates state machine from `phases.yml`

## Estimate

- **Complexity**: 2 (orchestration; lifecycle logic exists)
- **Uncertainty**: 2 (track variants may surface missing transitions)
- **Risk**: 0 (test code, not production)
- **Manual**: 1 (verify on dirty checkout)
- **Total**: 5 → **S-track**
- **Estimate**: 5 days

## Out of scope

- Mocking real LLM calls (fake agents write files, not LLM stubs)
- Network-dependent operations (publish adapters tested separately in KLC-003)
- Running against real rust-analyzer / scip-clang (those have integration tests)
- Performance profiling of phase agents
- Multi-ticket parallel execution

## Dependencies

None — this is the first ticket in the refactor sequence.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fake fixtures drift from real agent outputs | Medium | Pin fixture format to `process-artifacts.md` schema |
| Track-specific phases not covered | High | Parametrize test over all 4 tracks |
| Harness breaks on config changes | High | Load `phases.yml` dynamically, don't hardcode phase names |

## Questions

None.

## Related

- **Blocks**: KLC-007 (code refactor), KLC-009 (config cleanup)
- **Builds on**: `tests/smoke.py` (complements, doesn't replace)
- **Validates**: Lifecycle described in KLC-006 docs (future)

## Notes

Build first; KLC-007 and KLC-009 must not start until this is green.

Fake-agent pattern chosen per user request: agents are file-writers, not model simulators.
