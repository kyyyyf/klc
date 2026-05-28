# Review-lite phase (XS only)

## Purpose
Fast review for XS tickets. Basic sanity check, no detailed audit.

## Inputs
- Code changes from xs-build
- `spec.md`

## Outputs
- Review decision (approve/needs-rework)

## Process
Quick check:
- ACs met?
- Tests pass?
- No obvious issues?

## Completion criteria
- Basic validation complete
- No critical issues found

## Ack options
- `--pick 1` (approve): Advance to integrate:work
- `--pick 2` (needs-rework): Back to xs-build:work

## Common pitfalls
- Over-analyzing XS ticket (defeats fast-path purpose)

## Example
XS ticket: Typo fix + test → passes review → integrate
