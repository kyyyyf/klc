# Learn phase

## Purpose
Write retrospective. Capture what went well, what could improve, lessons learned, action items.

## Inputs
- All ticket artifacts (spec, test-plan, build-log, review-report, observe.md)
- Phase history from meta.json

## Outputs
- `retrospective.md`

## Process
Agent writes retrospective covering:
- What went well (successes)
- What could improve (friction, rework)
- Lessons learned (framework insights, process observations)
- Recommendations (for framework, for future tickets)
- Action items (concrete TODOs)

## Completion criteria
- retrospective.md exists with all sections
- Recommendations are actionable (not vague)
- Process metrics included (duration, rework cycles, blocked time)

## Ack options
- `--pick 1` (archive): Mark ticket as complete

## Common pitfalls
- Generic retrospective ("everything was good")
- No action items (missed opportunity to improve)
- Blaming instead of learning

## Example
S ticket: Retrospective notes 3 iterations in build, recommends better test-plan upfront → archive  
M ticket: Retrospective documents design phase prevented rework → archive
