# Discovery phase

## Purpose
Transform raw input into formal spec with ACs, estimate, track assignment.

## Inputs
- `raw.md`

## Outputs
- `spec.md` — formal specification (Goals, Problem, Solution, ACs, Estimate, Constraints, Affected modules)
- `meta.json` updated with track, estimate, layer, affected_modules

## Process
Agent reads raw.md, writes spec.md with:
- Acceptance criteria (AC-1, AC-2, ...)
- Estimate dimensions (complexity, uncertainty, risk, manual)
- Track assignment (XS/S/M/L based on total)
- Affected modules and layer

## Completion criteria
- spec.md exists with all required sections
- Every AC is testable
- Estimate total matches track

## Ack options
- `--pick 1` (approve): Seal spec.md, advance based on track
  - XS → xs-build:work
  - S/M/L → acceptance-test-plan:work
- `--pick 2` (needs-rework): Agent revises spec.md

## Common pitfalls
- Non-testable ACs (e.g., "improve performance" without metric)
- Wrong track assignment (human can override in meta.json)
- Scope creep (affected_modules too broad)

## Example
XS ticket: `klc ack KLC-123 --pick 1` → xs-build:work  
S ticket: `klc ack KLC-124 --pick 1` → acceptance-test-plan:work
