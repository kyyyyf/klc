---
ticket: KLC-02
kind: bug
authority: human
last_generated: 2026-05-28T09:00:00Z
---

# KLC-02 — klc ack rejects manual discovery completion

## Problem

`klc ack` blocks on `discovery:work` phase even when completion artifacts (spec.md, updated meta.json) are present. Forces agent runner invocation, prevents manual spec authoring.

> [!FACT F-001] src=scripts/klc verified=2026-05-28
> `klc ack` command exists and is the documented way to confirm phase completion per discovery/_prompt.md

> [!FACT F-002] src=KLC-001 reproduction verified=2026-05-28
> After manually creating spec.md and updating meta.json with track/estimate/affected_modules, `klc ack KLC-001` returns error: "ticket is in `discovery:work`; finish the work first"

## Goals

Enable manual discovery phase completion without requiring agent runner.

## Acceptance Criteria

1. **AC-1**: Given ticket in `discovery:work` with valid spec.md (has frontmatter, Goals, AC, Estimate sections) and meta.json (track, estimate, affected_modules set), `klc ack <KEY>` advances to `discovery:ack-needed`

2. **AC-2**: If spec.md missing or meta.json incomplete, `klc ack <KEY>` shows clear error listing missing fields (not generic "finish work first")

3. **AC-3**: Behavior is backward-compatible: agent-driven completion (via `DISCOVERY_SPEC_WRITTEN` signal) still works

4. **AC-4**: Documentation updated: discovery/_prompt.md clarifies that manual spec.md creation + `klc ack` is supported

## Non-goals

- Changing other phases (build, review, etc.) — only discovery for now
- Adding new commands like `klc complete-phase` — use existing `klc ack` semantics

## Constraints

> [!CONSTRAINT C-001] source=klc design
> Must not break existing agent-driven workflows. Agent runners emit `DISCOVERY_SPEC_WRITTEN` and rely on automatic state transition.

> [!CONSTRAINT C-002] source=ticket state machine
> Phase transitions must be atomic and logged in meta.json phase_history

## Affected modules

- `scripts/klc`: ack verb implementation (likely `cmd_ack` function)
- `scripts/klc` or similar: discovery phase state machine logic

## Technical approach

### Root cause analysis

Check `scripts/klc` for `cmd_ack` implementation:
1. Does it check `meta.json` phase field only, or also completion artifacts?
2. Is there a `discovery:ack-needed` intermediate state that agent runner sets, but manual path bypasses?
3. Does `--pick` mechanism apply to discovery phase?

### Proposed fix (after root cause confirmed)

**Option A**: Detection-based
```python
def cmd_ack(ticket_key):
    meta = load_meta(ticket_key)
    
    if meta["phase"] == "discovery:work":
        # Check if manual completion artifacts present
        spec_path = ticket_dir / "spec.md"
        if spec_path.exists() and is_valid_spec(spec_path) and meta.get("track") and meta.get("estimate"):
            # Advance to discovery:ack-needed
            transition_phase(ticket_key, "discovery:ack-needed", "manual-completion")
            print(f"→ discovery:ack-needed (manual spec detected)")
            return
        else:
            list_missing_artifacts(ticket_key)
            sys.exit(1)
    
    # ... existing ack logic for other phases
```

**Option B**: Explicit flag (more conservative)
```python
def cmd_ack(ticket_key, manual=False):
    if manual and meta["phase"] == "discovery:work":
        validate_artifacts_or_exit(ticket_key)
        transition_phase(ticket_key, "discovery:ack-needed", "manual-completion")
```

Preference: **Option A** (detection-based) — less friction, same as how `klc next` auto-detects phase readiness.

## Open questions

> [!QUESTION Q-001] blocks=design
> Does `scripts/klc` currently have artifact validation logic for any phase, or does it rely purely on phase state machine?
> **Resolution**: Read `scripts/klc` cmd_ack and related phase transition code.

> [!QUESTION Q-002] blocks=design
> Is `discovery:ack-needed` a real intermediate state, or does discovery go directly from `discovery:work` → next phase?
> **Resolution**: Check config/phases.yml and KLC-001 meta.json phase_history.

> [!QUESTION Q-003] blocks=none
> Should we add validation that spec.md frontmatter `ticket:` field matches the actual ticket key?
> **Resolution**: Yes if easy (1-liner), defer otherwise.

## Estimate

- complexity: 1 (modify existing cmd_ack logic)
- uncertainty: 1 (need to read scripts/klc to confirm structure, but likely straightforward)
- risk: 1 (could break agent workflows if validation too strict)
- manual: 0 (can test with KLC-001 and KLC-02 themselves)
- total: 3
- track: XS

## Test plan

1. **Baseline**: Reproduce issue with KLC-001 (already done)
2. **After fix**:
   - KLC-01: `klc ack KLC-01` should now advance to `discovery:ack-needed`
   - KLC-02: Apply same fix, verify `klc ack KLC-02` works
3. **Regression**: Create KLC-03 with agent-driven discovery, verify `DISCOVERY_SPEC_WRITTEN` signal still works
4. **Validation**: Remove `track` from meta.json, verify `klc ack` shows clear error about missing field

## Related tickets

- KLC-001: trigger for this bug (could not manually complete discovery)
