---
ticket: KLC-022
phase: design
authority: agent
---

# KLC-022 — Design

One option. Shape is determined by:
- forward pull reuses advance_to_next conditional-skip walk (KLC-014)
- backward pull reuses lifecycle.supersede_phases (already exists)
- direction auto-detected by phase index — no new user-facing discriminator

## Option A — adopted (only option)

### Direction detection

`track_phases(track)` → ordered list. Compare index of `--to` vs current:
- `--to` index > current → **forward**
- `--to` index < current → **backward**
- equal → noop / error

### Forward pull mechanics

Walk from current toward `--to` using same logic as `advance_to_next`:
1. For each phase on the path: evaluate `phase.should_run(meta)`.
   - `condition=False` → skip (write `event=skipped` to phase_history).
   - `phase.inputs` not all on disk → **STOP**, surface as artefact-missing.
2. At target phase: move klc via dedicated lifecycle op (see below).
3. Human sees two categories before proceeding:
   - `SKIPPED (condition)` — legitimate auto-skip, green.
   - `MISSING <file>` — blocks unless force.

### Backward pull mechanics

1. Collect phases between `--to` and current (inclusive of current).
2. Call `lifecycle.supersede_phases(ticket, phase_ids)` — moves artefacts
   to `_superseded/<ts>/`.
3. Confirm before superseding (TTY prompt; non-TTY aborts).
4. Set klc state to `<target>:work` via dedicated op.

### Dedicated lifecycle operation

New `lifecycle.jira_pull(ticket, target_phase, *, jira_status, force,
reason, missing_artifacts, skipped_phases)`:
- writes phase_history event `jira-pull` or `jira-force-pull`
- event fields: `jira_status`, `target_phase`, `missing_artifacts[]`,
  `skipped_phases[]`, `note=reason`
- does NOT go through normal ack/picks — direct state write with provenance

### jira_sync.pull() public API

```python
def pull(ticket: str, target_phase: str,
         force: bool = False, reason: str | None = None) -> dict:
    """Jira→klc state movement.
    Loads config/client internally (mirrors push()).
    Returns {ok, action, detail}.
    """
```

Internally: validate → detect direction → walk/supersede → jira_pull().

### Inline rework fork (AC-7)

In `lifecycle._prompt_conflict` (KLC-021), when plan has
`jira-moved-externally` AND direction is BACKWARD (Jira lower than klc):
- replace option 1 label with `pull klc → <candidate list>`
- candidate list = `cfg.jira_to_klc[plan.jira_status]` intersected with
  phases that exist in ticket's track
- on pick 1: call `jira_sync.pull(ticket, chosen_candidate)`

### Step plan (5 steps)

| Step | Files |
|------|-------|
| 1 | `core/skills/lifecycle.py` — `jira_pull()` op |
| 2 | `core/skills/jira_sync.py` — `pull()`, forward walk, backward supersede |
| 3 | `core/phases/jira.py` — `reconcile pull --to` + `force-pull --to --reason` |
| 4 | `core/skills/lifecycle.py` — update `_prompt_conflict` for rework fork |
| 5 | `tests/integration/test_jira_pull.py` + `docs/process.md` |

[!DECISION D-001] `jira_pull()` is a new low-level op separate from `jump()` —
it needs Jira provenance fields that `jump()` doesn't carry.
[!DECISION D-002] Backward pull always requires TTY confirm — no silent backward
moves; too destructive.
[!DECISION D-003] Forward pull stops at first missing-inputs phase unless
`force=True`; conditional skips are transparent (shown but not blocking).
