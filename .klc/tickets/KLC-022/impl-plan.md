# KLC-022 impl-plan

## step-1 — lifecycle.jira_pull() dedicated op

New low-level operation in `core/skills/lifecycle.py`.
Does NOT route through ack/picks. Writes provenance event to phase_history.

**Affected files**: `core/skills/lifecycle.py`

**Changes**:
```python
def jira_pull(ticket: str, target_phase: str, *,
              jira_status: str,
              force: bool = False,
              reason: str | None = None,
              missing_artifacts: list[str] | None = None,
              skipped_phases: list[str] | None = None) -> str:
    """Move klc to target_phase with Jira provenance. Returns new phase string."""
    event = "jira-force-pull" if force else "jira-pull"
    extra = {
        "jira_status": jira_status,
        "target_phase": target_phase,
        "missing_artifacts": missing_artifacts or [],
        "skipped_phases": skipped_phases or [],
    }
    if reason:
        extra["note"] = reason
    set_state(ticket, target_phase, STATE_WORK, event=event, extra=extra)
    return format_state(target_phase, STATE_WORK)
```

**Expected tests**: unit — phase_history contains correct event fields.

**Rollback**: delete function

---

## step-2 — jira_sync.pull() with forward/backward dispatch

New `pull(ticket, target_phase, force, reason)` in `core/skills/jira_sync.py`.

**Affected files**: `core/skills/jira_sync.py`

**Changes**:
- `pull()` public wrapper (mirrors `push()` — loads config/client).
- `_pull_impl(ticket, target_phase, force, reason, client, cfg)` internal.
- Direction detection: `phases.load_phases().track_phases(track)` index comparison.
- Forward walk: iterate phases between current and target; call
  `phase.should_run(meta)` for conditional check; check `phase.inputs` for
  artefact presence.
- Backward: call `lifecycle.supersede_phases(ticket, phase_ids_to_supersede)`.
- Both paths call `lifecycle.jira_pull()` for the final state write.

**Expected tests**:
- forward pull skips conditional phase → event=skipped in history
- forward pull stops at missing inputs → ok=False, suggests force-pull
- backward pull → supersede called, jira_pull called with backward phases

**Rollback**: delete pull() and _pull_impl()

---

## step-3 — jira.py: reconcile pull + force-pull subcommands

**Affected files**: `core/phases/jira.py`

**Changes**:
Add to `cmd_reconcile`:
- `pull --to <phase>`: validate → `jira_sync.pull(ticket, phase)` → print result.
  If stops due to missing inputs: show two-section output (SKIPPED vs MISSING).
  If backward: TTY confirm prompt before proceeding.
- `force-pull --to <phase> --reason "..."`: `jira_sync.pull(ticket, phase,
  force=True, reason=...)`.

**Expected tests**: CLI exit codes, output format, non-TTY backward aborts.

**Rollback**: revert cmd_reconcile

---

## step-4 — lifecycle._prompt_conflict: inline rework fork

**Affected files**: `core/skills/lifecycle.py`

**Changes**:
In `_prompt_conflict`, when `plan.has_conflict("jira-moved-externally")` AND
Jira moved backward (plan.jira_status maps to phases earlier than current):
- replace option 1 text with candidates from `cfg.jira_to_klc[jira_status]`
  filtered to ticket's track
- on pick 1: call `jira_sync.pull(ticket, chosen)` with confirm

**Expected tests**:
- backward PM-move → candidates shown in prompt
- pick 1 → pull executed, supersede called

**Rollback**: revert _prompt_conflict

---

## step-5 — tests + docs

`tests/integration/test_jira_pull.py` covering all AC (FakeJiraClient,
no network). `docs/process.md` pull/force-pull semantics section.

**Expected tests**: all AC from test-plan pass.
