# XS-build phase (XS only)

## Purpose
Fast-path build: combine test writing and implementation in single step. No test-plan.md required.

## Inputs
- `spec.md`

## Outputs
- Code changes
- Tests (inline or separate files)
- Git commit

## Process
Agent writes tests and implementation together. No TDD loop, no impl-plan.md. Single iteration expected.

## Completion criteria
- All ACs met
- Tests pass
- Code committed

## Ack options
- `--pick 1` (approve): Advance to review-lite:work
- `--pick 2` (needs-rework): Agent fixes code/tests

## Common pitfalls
- Overcomplicating XS ticket (should be trivial)
- Missing tests (even XS needs test coverage)

## Example
XS ticket: Fix typo + add test → commit → approve → review-lite
