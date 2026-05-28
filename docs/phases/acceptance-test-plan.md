# Acceptance-test-plan phase

## Purpose
Map every AC to concrete acceptance/e2e tests. No implementation details yet.

## Inputs
- `spec.md`

## Outputs
- `test-plan.md` — Acceptance coverage table, edge cases, regression scenarios, manual checklist (if estimate.manual ≥ 2)

## Process
Agent writes test-plan.md with:
- Table: AC | Test type (e2e/acceptance/manual) | Test location | Notes
- Edge cases from spec
- Regression scenarios for affected modules
- Manual checklist if needed

## Completion criteria
- Every AC has a row in acceptance coverage table
- Test types are e2e/acceptance/manual (no unit/integration yet)
- Manual checklist populated if estimate.manual ≥ 2

## Ack options
- `--pick 1` (approve): Advance based on track
  - S → build:work
  - M/L → design:work
- `--pick 2` (needs-rework): Agent revises test-plan.md

## Common pitfalls
- Missing AC in table → phase failure
- Using unit/integration test types (those are phase 4 concern)
- No manual checklist when estimate.manual ≥ 2

## Example
S ticket: AC-1, AC-2, AC-3 → 3 rows in table → approve → build:work  
M ticket: AC-1, AC-2 → 2 rows → approve → design:work
