# KLC-02 Design — Manual discovery completion support

## Root cause confirmed

> [!FACT F-003] src=core/phases/ack.py:50-56 verified=2026-05-28
> `klc ack` rejects any ticket in `<phase>:work` state with error "finish the work first". No artifact detection logic.

Current ack.py logic:
```python
pid, state = _ph.parse_state(cur)
if state == _ph.STATE_WORK:
    sys.stderr.write(
        f"klc ack: ticket is in `{cur}`; finish the work first "
        f"(or `klc abort {args.ticket}` to cancel).\n"
    )
    return 1
```

The only valid states for `klc ack` are `:ack-needed` and `:ack` (which redirects to `klc next`).

## Architecture

Phase state machine (from phases.yml):
```
discovery:work → discovery:ack-needed → discovery:ack → (next phase)
```

Agent workflow:
1. Agent reads `discovery/_prompt.md`
2. Agent writes `spec.md` + updates `meta.json`
3. Agent emits `DISCOVERY_SPEC_WRITTEN <key>` to stdout
4. Runner script (not in ack.py) catches signal, transitions `discovery:work` → `discovery:ack-needed`
5. Human runs `klc ack <key>` to confirm
6. Advances to next phase

**Problem**: Step 4 is missing for manual workflows. Artifacts exist but phase is stuck at `:work`.

## Design options

### Option A: Artifact detection in ack.py (RECOMMENDED)

Modify `ack.py` to detect completion artifacts when in `:work` state:

```python
if state == _ph.STATE_WORK:
    # Special case: discovery phase with manual completion
    if pid == "discovery" and _has_discovery_artifacts(args.ticket):
        # Auto-advance to ack-needed
        _lc.force_transition(args.ticket, f"discovery:ack-needed", 
                             event="manual-completion", note="artifacts detected")
        # Recurse: now in ack-needed, normal ack logic applies
        return run(argv)
    
    sys.stderr.write(...)  # existing error
    return 1
```

Helper:
```python
def _has_discovery_artifacts(ticket: str) -> bool:
    """Check if spec.md + meta.json completion fields present."""
    ticket_dir = klc_ticket_meta_file(ticket).parent
    spec = ticket_dir / "spec.md"
    if not spec.exists():
        return False
    
    meta = _lc.read_meta(ticket)
    if not meta.get("track") or not meta.get("estimate"):
        return False
    
    # Optional: validate spec.md has required sections
    return True
```

**Pros**:
- No new commands/flags
- Works for existing workflow: human creates artifacts, runs `klc ack`
- Backward compatible: if artifacts missing, shows existing error

**Cons**:
- Adds phase-specific knowledge to ack.py (violates "no phase-specific knowledge" comment)
- Only handles discovery phase; other phases would need similar logic

### Option B: New `klc complete` command

Add `core/phases/complete.py`:
```python
def run(argv):
    """Force-complete a :work phase by validating artifacts."""
    ticket = argv[0]
    meta = _lc.read_meta(ticket)
    pid, state = _ph.parse_state(meta["phase"])
    
    if state != _ph.STATE_WORK:
        sys.stderr.write(f"klc complete: ticket not in :work state\n")
        return 1
    
    if pid == "discovery":
        if not _has_discovery_artifacts(ticket):
            sys.stderr.write("Missing: spec.md or meta.json fields\n")
            return 1
        _lc.force_transition(ticket, "discovery:ack-needed", "manual-completion")
        print(f"→ discovery:ack-needed (manual completion)")
        print(f"  next: klc ack {ticket}")
    else:
        sys.stderr.write(f"klc complete: phase {pid} not supported\n")
        return 1
```

Usage: `klc complete KLC-001` → advances to `:ack-needed`.

**Pros**:
- Explicit intent (human signals "I completed this manually")
- Keeps ack.py clean
- Easy to extend to other phases

**Cons**:
- New command to learn
- Extra step: `klc complete` then `klc ack` instead of just `klc ack`

### Option C: `klc ack --force` flag

Add `--force` flag to ack.py:
```python
ap.add_argument("--force", action="store_true",
                help="Force completion if artifacts present (manual workflow)")

if state == _ph.STATE_WORK:
    if args.force and pid == "discovery" and _has_discovery_artifacts(ticket):
        # transition to ack-needed, then apply normal ack
        ...
    else:
        sys.stderr.write(...)
        return 1
```

**Pros**:
- Explicit opt-in (safer than auto-detection)
- Single command: `klc ack KLC-001 --force`

**Cons**:
- Flag name collision risk (`--force` often means "skip validation")
- Still adds phase-specific knowledge to ack.py

## Recommendation

**Option A** (artifact detection) with refinements:
- Extract phase-specific completion checks to separate module `core/skills/phase_completion.py`
- ack.py imports and calls `phase_completion.can_complete(ticket, phase_id)` → bool
- Keeps ack.py generic, phase logic centralized

Implementation:
1. Create `core/skills/phase_completion.py` with `can_complete_discovery(ticket) -> bool`
2. Modify `ack.py` lines 50-56 to call `phase_completion.can_complete()` before rejecting
3. If `can_complete()` returns True, call `lifecycle.force_transition()` to `:ack-needed`, then recurse
4. Add tests: KLC-001 should now complete, KLC-02 should complete after fix applied

## Open questions resolved

> [!FACT F-004] src=core/phases/ack.py:50 verified=2026-05-28
> Q-001 answer: ack.py only checks `state` field, not artifacts.

> [!FACT F-005] src=KLC-001/meta.json phase_history verified=2026-05-28
> Q-002 answer: Yes, `discovery:ack-needed` is a real intermediate state. intake → discovery:work → discovery:ack-needed → discovery:ack → (next).

> [!DECISION D-001]
> Q-003: Yes, add frontmatter validation (ticket field must match directory name). Prevents copy-paste errors.

## Files to modify

1. **Create**: `core/skills/phase_completion.py`
   - `can_complete_discovery(ticket: str) -> tuple[bool, str]` — returns (success, error_msg)
   - Checks: spec.md exists, has frontmatter with correct ticket field, meta.json has track/estimate/affected_modules

2. **Modify**: `core/phases/ack.py` lines 50-56
   - Before rejecting `:work` state, call `phase_completion.can_complete(ticket, pid)`
   - If True, force-transition to `:ack-needed`, recurse `return run(argv)`
   - If False, show enhanced error with specific missing fields

3. **Update**: `core/agents/discovery.md` (if exists) or `discovery/_prompt.md` template
   - Document that manual spec.md + `klc ack` is supported

## Test acceptance

After implementation:
```bash
# Should now work:
cd /mnt/d/a_work/klc
./scripts/klc ack KLC-001

# Expected output:
# → discovery:ack-needed (manual completion detected)
# next: klc ack KLC-001 (or use --pick if needed)

# Then:
./scripts/klc ack KLC-001
# → next phase (acceptance-test-plan for S track)
```

## Estimate refined

After design: 2-3 hours implementation + testing.
- 1h: write phase_completion.py with validation logic
- 0.5h: modify ack.py
- 0.5h: test with KLC-001, KLC-02
- 0.5h: document in prompt template

Complexity remains 1 (straightforward validation + state transition), total estimate unchanged.
