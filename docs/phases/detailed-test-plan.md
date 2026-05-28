# Detailed-test-plan phase (M/L only)

## Purpose
Add unit/integration tests keyed to impl-plan steps. Extends test-plan.md.

## Inputs
- Existing `test-plan.md` (acceptance section)
- `impl-plan.md`
- `design/adr.md`

## Outputs
- `test-plan.md` updated with "Detailed coverage" section

## Process
Agent appends "Detailed coverage" table to test-plan.md:
- Table: step | Test type (unit/integration/characterisation) | Test location | Target symbol(s) | Notes
- Every impl-plan step must appear or have "covered-by: AC-N" note

## Completion criteria
- Every step from impl-plan.md has a row or covered-by reference
- Test types are unit/integration/characterisation (not e2e/acceptance)
- Target symbols verified via LSP (no hallucinated names)

## Ack options
- `--pick 1` (approve): Advance to build:work
- `--pick 2` (needs-rework): Agent revises detailed coverage section

## Common pitfalls
- Missing step in table (no covered-by note)
- Target symbol doesn't exist (agent hallucinated name)
- Duplicate acceptance tests at detailed level

## Example
M ticket: step-1 → unit test, step-2 → integration test, step-3 → covered-by: AC-1 → approve → build:work
