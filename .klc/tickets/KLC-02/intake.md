# KLC-02: klc ack doesn't accept manual discovery completion

## Problem

When working on KLC-001, after manually creating `spec.md` and updating `meta.json` with track/estimate/affected_modules, running `klc ack KLC-001` fails with:

```
klc ack: ticket is in `discovery:work`; finish the work first (or `klc abort KLC-001` to cancel).
```

Expected: `klc ack` should detect that discovery outputs are complete (spec.md exists, meta.json has track) and advance to `discovery:ack-needed`.

## Steps to reproduce

1. `klc intake KLC-001 --kind feature "description"`
2. `klc ack KLC-001` → advances to `discovery:work`
3. Manually create `/mnt/d/a_work/.klc/tickets/KLC-001/spec.md` with full spec
4. Manually update `meta.json` with `track: "S"`, `estimate: {...}`, `affected_modules: [...]`
5. Run `klc ack KLC-001`

**Actual**: Error "finish the work first"
**Expected**: Advance to `discovery:ack-needed` or prompt for pick

## Context

The discovery phase prompt says:
> When done: `klc ack KLC-001` (with --pick if required)

But `klc ack` seems to expect discovery agent to run and emit `DISCOVERY_SPEC_WRITTEN` via some internal mechanism, not manual file creation.

## Impact

- Cannot manually complete discovery phase without agent
- Blocks self-hosting use case (using klc to improve klc)
- Forces full agent run even for simple tickets where human already knows the spec

## Possible root causes

1. `klc ack` checks phase state, not completion artifacts
2. Discovery phase requires agent runner to transition state
3. Missing manual completion path (like `klc ack KLC-001 --force-complete`)

## Desired behavior

One of:
- **Option A**: `klc ack` detects spec.md + updated meta.json → auto-advance
- **Option B**: Add `klc ack KLC-001 --manual` flag to signal manual completion
- **Option C**: Add `klc complete-phase KLC-001 discovery` command for manual phase completion

## Environment

- klc version: current main branch (commit c4b4d3a)
- Ticket: KLC-001 (track S, discovery:work)
- Manual spec creation via Write tool, not agent runner
