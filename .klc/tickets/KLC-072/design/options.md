---
ticket: KLC-072
kind: bug
authority: agent
---

# KLC-072 — design options

Design confirms the discovery pick (Option A — minimal, targeted fixes). Below
are the concrete design choices per bug.

## Option A (chosen) — targeted routing/parse fixes

### Bug 1 & 2 — dispatcher order (scripts/klc)

Remove `metrics`, `reindex`, and `jira-sync` from `OPERATIONAL_CMDS` (none has a
`core/phases/<name>.py`, so the generic `_run_phase` route can never serve them
correctly), and add an explicit `jira-sync` handler that routes to the real
wrapper module `jira_sync_cmd.py`. The existing explicit `metrics`/`reindex`
handlers then become reachable. `OPERATIONAL_CMDS` keeps only the verbs that DO
have a phase file (`board`, `doctor`, `install`, `jira`, `setup`, `state`), so the
generic route stays correct and the "which verbs are phase-backed" invariant is
restored. Help text keeps documenting all verbs.

Rejected alternative for bug 2: renaming `jira_sync_cmd.py` to `jira_sync.py`.
It would let the generic route work but breaks every existing importer of
`jira_sync_cmd` and collides conceptually with the `jira_sync` skill module.

### Bug 3 — resolveFrameworkRoot (klcReader.ts)

Add a `KLC_FW` matcher as the primary pattern (covers bash `KLC_FW="..."`, cmd
`set "KLC_FW=..."`, and PowerShell `$env:KLC_FW = '...'` with one tolerant
regex), keeping `KLC_FRAMEWORK_ROOT` and `$FW` as legacy fallbacks.

### Bug 4 — per-step card + required pick (status.py + klcReader.ts + treeProvider.ts)

Introduce one helper on each side that, for `build:work`, resolves
`build/_prompt_step_<impl_step>.md` (default step 1) and renders the ack command
with the required single pick when the phase declares exactly one required pick.
`status.py._next_hint` and the VS Code reader/tree both consume it.

## Option B — command registry (rejected)

See spec. Larger blast radius than a bug fix warrants.

## Option C — phase-file wrappers (rejected)

See spec. Adds indirection files and a risky rename.

Picked: Option A.
