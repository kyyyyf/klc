# Build phase (S/M/L)

## Purpose
Implement code via TDD loop. Make failing tests pass, one step at a time.

## Inputs
- `spec.md`
- `test-plan.md`
- `impl-plan.md` (M/L only)

## Outputs
- Code changes
- `build-log.md` — iteration journal
- Git commits (one per step when practical)

## Process
TDD loop:
1. Test agent writes failing test for step-N
2. Verifier confirms red
3. Impl agent makes test pass
4. Verifier confirms green
5. Repeat for next step

S-track: Work from spec.md directly  
M/L-track: Follow impl-plan.md steps

## Completion criteria
- All tests green
- All ACs have corresponding passing tests
- build-log.md records all iterations and has a `## Evidence` section with at least one non-empty fenced block
- impl-plan.md fully ticked (M/L only)
- Git history shows a failing-test commit before the implementation commit for each behaviour step (verified mechanically by `klc ack` via `core/skills/tdd_order.py`; steps with `RED: not applicable` are exempt)

## Ack options
- `--pick 1` (approve): Advance to review:work
- `--pick 2` (blocked): Budget limit hit or plan invalid

## Common pitfalls
- Red test loop (>3 iterations) → budget limit
- Scope creep (touching files outside affected_modules)
- Silent plan changes (must add [!DECISION] items)

## Example
S ticket: 3 steps → all green → approve → review:work  
M ticket: impl-plan has 5 steps → all ticked → approve → review:work
