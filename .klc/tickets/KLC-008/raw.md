---
ticket: KLC-008
kind_hint: tech
created: 2026-05-28T11:15:11Z
---
# KLC-008 — E2E test infrastructure: fake-agent pipeline

## Context

Existing tests:
- `tests/smoke.py` (517 lines): tests pipeline machinery in 14 blocks, but doesn't run a ticket through full lifecycle
- `tests/test_callgraph_rust_lsp.py`: integration test for one skill

Gap: no test verifies that a ticket can transition through every phase (intake → discovery → … → archived) with all artefacts written, ack rules enforced, and state machine consistent.

This means refactors (KLC-007) and config changes (KLC-009) can silently break the lifecycle.

## Problem

We need a regression-proof harness that:
1. Creates a fake ticket
2. Drives it through every phase using **fake agents** (deterministic stub agents that produce canned artefacts)
3. Verifies each phase's ack succeeds and state transitions correctly
4. Cleans up after itself

This must run fast (<60s) so it can be invoked locally and in CI.

## Proposed solution

**`tests/e2e_pipeline.py`** — new harness:

```
1. setup: create temp .klc/ root with minimal config/profile/reviewers
2. seed: create fake ticket with intake stub
3. for each phase in lifecycle:
     - invoke "fake agent" that writes the expected artefacts (spec.md, design.md, etc.)
       using fixtures/fake-agent-outputs/<phase>.md
     - run `klc ack <KEY>` (programmatic, not subprocess)
     - assert phase advanced
     - assert required artefacts exist
4. assert final state == archived
5. teardown: rm -rf temp dir
```

**`tests/fixtures/fake-agent-outputs/`** — canned artefact bodies for every phase:
- `intake.md`, `discovery.md`, `acceptance-test-plan.md`, `impl-plan.md`, `build-log.md`, `review-report.md`, `integrate.md`, `observe.md`, `retrospective.md`

**Track variants**: parametrize the harness over tracks XS / S / M / L so each path is exercised.

**CI hook**: add `make test-e2e` (or equivalent) that runs `e2e_pipeline.py` after `smoke.py`.

**Unit tests for skills** (lighter additions):
- `tests/test_phase_completion.py` — asserts each phase's completion check returns expected bool
- `tests/test_lifecycle.py` — asserts state machine rejects invalid transitions

## Acceptance criteria

- AC-1: `python tests/e2e_pipeline.py` exits 0 on a clean checkout
- AC-2: All 4 tracks (XS/S/M/L) tested; each runs through its phase set without error
- AC-3: For each phase, harness asserts artefacts written match `core/agents/<phase>.md` declared outputs
- AC-4: Total runtime <60s on developer machine
- AC-5: Harness leaves no residue (temp dir cleaned in `finally`)
- AC-6: Failure messages name the phase, ticket key, and missing/extra artefact
- AC-7: `tests/test_phase_completion.py` covers every phase listed in `config/phases.yml`

## Out of scope

- Mocking real LLM calls (fake agents are file-writers, not LLM stubs)
- Network-dependent operations (publish adapters from KLC-003 use their own tests)
- Running against real rust-analyzer / scip-clang (those have their own fixtures)

## Estimate

- Complexity: 2 (mostly orchestration; lifecycle logic exists)
- Uncertainty: 2 (track variants may surface missing transitions)
- Risk: 0 (tests, not production code)
- Manual: 1 (verify harness on dirty checkout)
- Total: 5
- Track: S

## Related

- **Blocks KLC-007** (code refactor) — refactor needs this safety net
- **Blocks KLC-009** (config cleanup) — same reason
- Builds on `tests/smoke.py` (existing 14-block machinery test) — complement, not replacement
- Validates lifecycle described in KLC-006 docs

## Notes

Build first; KLC-007 and KLC-009 should not start until this is green.

Fake-agent pattern (per user request): the agent stub literally just `cat` a fixture into the artefact path. No simulation of model behavior.
