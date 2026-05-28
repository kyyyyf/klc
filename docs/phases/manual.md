# Manual phase (M/L only)

## Purpose
Human manual validation/testing before integration. For tickets with high manual estimate (≥2).

## Inputs
- Code from build+review
- `test-plan.md` manual checklist
- `spec.md`

## Outputs
- Manual checklist completion confirmation
- Notes on any issues found

## Process
Human performs manual steps:
- Staging deployment test
- Visual inspection
- Manual QA scenarios
- Performance validation

## Completion criteria
- All manual checklist items checked
- No critical issues blocking merge

## Ack options
- `--pick 1` (pass): Advance to integrate:work
- `--pick 2` (fail): Back to build:work with findings

## Common pitfalls
- Skipping manual validation (defeats purpose)
- Checklist too vague ("test the feature")
- No rollback plan if manual test fails in prod

## Example
M ticket: Manual checklist has 3 items → human validates all → pass → integrate:work
