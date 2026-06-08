---
ticket: KLC-021
phase: design
authority: agent
---

# KLC-021 — Design

One option. No architectural alternatives — the shape is determined by
the constraint that mirror-mode behaviour must remain identical (regression
risk = zero for existing users), and managed-mode adds interactivity
without coupling to the lifecycle's internal logic.

## Option A — adopted

### Overview

Three orthogonal changes:

1. **`jira_sync.py`**: add `build_plan()` + `push()` — the new explicit
   push API used by `jira.py reconcile push` and the interactive hook.
2. **`lifecycle.py`**: make `push_phase` mode-aware — mirror = today's
   auto-push; managed = detect divergence + interactive prompt.
3. **`doctor.py`**: surface `meta.jira_sync.conflicts` as warnings.

### SyncPlan dataclass (jira_sync.py)

```python
@dataclass
class SyncPlan:
    ticket: str
    klc_phase: str               # full phase:state
    jira_status: str | None      # current Jira status (None if unreachable)
    target_status: str | None    # klc_to_jira[phase_id]
    last_jira_status: str | None # from meta.jira_sync (last known)
    in_sync: bool
    transition_id: str | None    # found transition if available
    conflicts: list[dict]        # [{type, detail}]
```

`build_plan(ticket, client, cfg) -> SyncPlan` — pure read, no writes.
Detects: in-sync, klc-moved, PM-moved-externally (current != last AND
current != target), issue-missing.

### push(ticket, client, cfg) -> dict

Uses `build_plan()` internally. Returns `{ok: bool, action: str, detail: str}`.
Single-hop: finds transition by name match → `transition_issue()` → adds
"moved by klc" comment. No transition → conflict recorded, returns `ok=False`.

### lifecycle.push_phase — mode-aware

```
load jira_config (cached, never raises)
if not enabled → return (no-op, same as today)
if mode == "mirror" → existing auto-push path (UNCHANGED)
if mode == "managed":
    ticket in managed_tickets? (or managed_tickets empty = all)
    build_plan(ticket, client, cfg)
    if plan.in_sync → return (no prompt needed)
    if TTY:
        if klc_moved (not PM conflict):
            prompt "Push Jira to {target}? [1=yes 2=skip]"
        else (PM conflict: jira-moved-externally):
            prompt "Jira changed externally. [1=push back 2=keep 3=skip]"
        handle choice
    else (non-TTY):
        record divergence in meta.jira_sync.conflicts, stderr warn
```

Key constraint: **never block ack**. If Jira is unreachable or config
broken → log warning, return. lifecycle.set_state must complete.

### managed_tickets scope

`managed_tickets: []` (empty or absent) = ALL tickets for this project.
`managed_tickets: [KLC-021, KLC-022]` = only those tickets.
Tickets NOT in the list when managed_tickets is non-empty → mirror behaviour.

### doctor.py conflict surfacing

New check `jira-sync-conflicts` added to CHECKS list. Scans all live
tickets' `meta.json:jira_sync.conflicts`. Non-empty → FAIL with details.
By default this check does NOT fail doctor (added as warn-only like
`project-tools`), configurable via `--strict`.

### impl-plan structure

5 steps:

| Step | Files |
|------|-------|
| 1 | `config/jira.yml` (managed_tickets), `validate_config.py` |
| 2 | `core/skills/jira_sync.py` — SyncPlan, build_plan(), push() |
| 3 | `core/skills/lifecycle.py` — mode-aware push_phase |
| 4 | `core/phases/doctor.py` — jira-sync-conflicts check |
| 5 | `tests/integration/test_jira_managed.py` + `docs/process.md` |

[!DECISION D-001] build_plan() is pure (no writes) — enables dry-run and
testing without mocking lifecycle.
[!DECISION D-002] push_phase never blocks ack — all Jira errors are
non-fatal warnings.
[!DECISION D-003] managed_tickets empty = all tickets in managed mode.
[!DECISION D-004] doctor jira-sync-conflicts is warn-only by default
(same pattern as project-tools check).
