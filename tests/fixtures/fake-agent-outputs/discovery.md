---
ticket: TEST-001
kind: feature
authority: agent
classification:
  complexity: 1
  uncertainty: 0
  risk: 0
  manual: 0
  total: 1
track: XS
estimate_days: 1
layer: code
affected_modules:
  - test-module
---

# TEST-001 — Fake ticket for E2E testing

## Goals

Validate E2E pipeline harness by simulating a minimal feature ticket.

## Problem / Context

E2E tests need a deterministic fake ticket that exercises the lifecycle state machine without requiring real work.

## Acceptance Criteria

- **AC-1**: Ticket transitions through all phases for its track
- **AC-2**: All artefacts generated per phases.yml outputs

## Non-goals

- Real functionality
- LLM interaction

## Constraints

None.

## Affected modules

- `test-module`: Fake module for testing

## Open questions

None.

## Estimate

- **Complexity**: 1 (trivial)
- **Uncertainty**: 0 (fully known)
- **Risk**: 0 (test fixture)
- **Manual**: 0 (automated)
- **Total**: 1 → **XS-track**
- **Estimate**: 1 day
