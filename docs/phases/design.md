# Design phase (M/L only)

## Purpose
Generate design options, choose one, document in ADR.

## Inputs
- `spec.md`
- `test-plan.md`

## Outputs
- `design/options.md` — 2-4 design approaches with trade-offs
- `design/adr.md` — chosen option, rationale, rejected alternatives

## Process
Agent writes options.md with multiple approaches, then writes adr.md documenting the chosen option and why.

## Completion criteria
- options.md lists 2-4 distinct approaches
- adr.md clearly identifies chosen option with rationale
- Chosen option is feasible (no hallucinated APIs)

## Ack options
- `--pick 1` (approve): Seal design, advance to detailed-test-plan:work
- `--pick 2` (needs-rework): Agent revises options/adr
- `--pick 3` (escalate): Design infeasible, requires human decision

## Common pitfalls
- Only 1 option (not enough exploration)
- Chosen option depends on nonexistent library/API
- Rationale missing (why this option vs others?)

## Example
M ticket: 3 options → choose option 2 (balances speed/maintainability) → approve → detailed-test-plan:work
