# Observe phase (S/M/L only)

## Purpose
Monitor metrics and stability for 24h post-merge. Detect regressions early.

## Inputs
- Merged code on main
- Baseline metrics (pre-merge)

## Outputs
- `observe.md` — metrics, alerts, rollback assessment

## Process
Agent or human monitors:
- Runtime metrics (latency, throughput, errors)
- Test stability (flakiness, failures)
- Integration health (downstream impacts)
- User feedback (bug reports, incidents)

## Completion criteria
- 24h monitoring window complete
- observe.md documents findings
- Rollback decision made (none/needed)

## Ack options
- `--pick 1` (stable): Advance to learn:work
- `--pick 2` (rollback): Revert merge, return to build:work

## Common pitfalls
- Ignoring error rate spike (false sense of stability)
- No rollback plan (can't revert quickly if needed)
- Monitoring window too short (issues appear after 24h)

## Example
S ticket: 24h pass → no alerts → stable → learn:work  
M ticket: Error rate +20% at 12h → investigate → rollback → build:work
