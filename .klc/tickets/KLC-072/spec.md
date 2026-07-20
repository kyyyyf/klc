---
ticket: KLC-072
kind: bug
authority: human
last_generated: 2026-07-20T00:00:00Z
risk_tags: [cli, dispatch, vscode]
---

# KLC-072 — spec: fix CLI + VS Code dispatch bugs

## Goals

Restore correct dispatch/parsing for four verbs and surfaces so operational
commands and the VS Code companion report reality:

- `klc metrics` / `klc reindex` reach their real handlers instead of printing
  "command not implemented".
- `klc jira-sync` reaches its wrapper (`jira_sync_cmd.py`).
- The VS Code tree resolves the framework from the installed shim's `KLC_FW`.
- The "next action" at `build:work` names the current per-step card and the
  required single pick.

## Problem

Four pre-existing dispatch bugs (surfaced during KLC-070 drift review) make
operational verbs and the VS Code companion misreport reality. None are part of
the planning-index epic; each is a routing/parsing mismatch.

## Root causes (verified against current code)

1. **`klc metrics` / `klc reindex` → "command not implemented".**
   In `scripts/klc`, both names are listed in `OPERATIONAL_CMDS`, and the branch
   `if cmd in LIFECYCLE_CMDS or cmd in OPERATIONAL_CMDS: return _run_phase(...)`
   (line ~147) runs BEFORE the explicit `reindex`/`metrics` handlers (lines
   ~150-160). `_run_phase` looks for `core/phases/metrics.py` /
   `core/phases/reindex.py`, which do not exist, so it prints
   "command not implemented" and returns 2. The real handlers are unreachable.

2. **`klc jira-sync` fails.** `jira-sync` is also in `OPERATIONAL_CMDS`, so it is
   routed via `_run_phase("jira-sync", ...)`, which resolves to
   `core/phases/jira_sync.py` (`-`→`_`). The actual wrapper is
   `core/phases/jira_sync_cmd.py`, so the file is not found →
   "command not implemented".

3. **VS Code extension can't find the framework.**
   `vscode-extension/src/klcReader.ts` `resolveFrameworkRoot()` parses
   `KLC_FRAMEWORK_ROOT=...` and `$FW = "..."`, but `klc install` writes the shim
   with `KLC_FW="..."` (bash/cmd) and `$env:KLC_FW = '...'` (PowerShell). Neither
   pattern matches, so the function returns `null` and the tree reports
   "klc framework not found".

4. **Wrong "next action" during build.**
   Build prompt cards are per-step: `build/_prompt_step_<impl_step>.md`
   (default step 1), written by `klc step`. But `core/phases/status.py`
   (`_next_hint`) and `vscode-extension/src/klcReader.ts` (`buildTicketState`
   omits the step) look only for `build/_prompt.md`, so at `build:work` they miss
   the real card. They also omit build's required single pick: the "when done"
   ack hint should be `klc ack <ticket> --pick 1` (build's ack has
   `pick_required: true` with a single pick `1=approve`), not a bare `klc ack`.

## Acceptance Criteria

- **AC-1** `klc metrics <ticket>` and `klc metrics --rollup` reach the real
  metrics handler (no "command not implemented"); `klc reindex <ticket>` reaches
  the items index handler. `klc reindex`/`klc metrics` with no args still print
  their usage (exit 2), not "command not implemented".
- **AC-2** `klc jira-sync` dispatches to `jira_sync_cmd.py` (its `run()` runs),
  no "command not implemented".
- **AC-3** `resolveFrameworkRoot()` returns the framework path from a shim that
  declares `KLC_FW` in any of the three installed forms (bash `KLC_FW="..."`,
  cmd `set "KLC_FW=..."`, PowerShell `$env:KLC_FW = '...'`). Legacy
  `KLC_FRAMEWORK_ROOT` / `$FW` remain accepted as fallback.
- **AC-4** At `build:work`, `status.py` resolves `build/_prompt_step_<step>.md`
  for the current `impl_step` (default 1) and the "when done" hint names the
  required single pick (`klc ack <ticket> --pick 1`). The VS Code reader
  (`buildTicketState`) resolves the per-step card for build, and `buildAckCommand`
  emits `--pick <id>` when the phase requires exactly one pick.
- **AC-5** No regression: existing `jira`, `board`, `doctor`, `state`, `install`,
  `setup` routing and non-build `:work` hints are unchanged. Full Python
  regression stays green.

## Approaches

### Option A — minimal, targeted routing/parse fixes

Reorder `scripts/klc` dispatch so explicit `metrics`/`reindex`/`jira-sync`
handlers run before the generic `_run_phase` route (and route `jira-sync` to
`jira_sync_cmd.py`); teach `resolveFrameworkRoot` the `KLC_FW` form; make
`status.py` + the VS Code reader resolve the per-step build card and the required
single pick. Small surface, fully covered by unit tests.

### Option B — restructure the dispatcher into a command registry

Replace the `LIFECYCLE_CMDS`/`OPERATIONAL_CMDS` tuples with an explicit
`{name: handler}` table so unreachable-handler bugs cannot recur. Cleaner
long-term but a larger blast radius and out of proportion for a bug ticket.

### Option C — move the verbs into real `core/phases/*.py` wrappers

Move `metrics`/`reindex`/`jira-sync` into real phase files so the generic route
works unchanged. Avoids reordering but adds three thin indirection files and
renames the existing `jira_sync_cmd.py`.

Picked: Option A — smallest change that fixes all four root causes with direct
test coverage; B and C carry more risk than a verified bug fix warrants.

## Estimate

Low complexity, low uncertainty (all four root causes verified against current
code), low-moderate risk (dispatch/parse changes touch shared entry points, so
regression coverage matters), minimal manual work.

- complexity: 2
- uncertainty: 1
- risk: 2
- manual: 1
- total: 6

## Out of scope

Planning-index epic work; new VS Code test harness (none exists — TS verified by
parsing logic + a Python-side status.py test).
