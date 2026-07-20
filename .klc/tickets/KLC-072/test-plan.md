---
ticket: KLC-072
kind: bug
authority: agent
---

# KLC-072 — Acceptance test plan

Tests are written RED-first against the four verified root causes, then the fix
turns them GREEN. Python-side tests drive `scripts/klc` and `status.py`
directly; the VS Code `.ts` fixes (no test harness in the extension) are covered
by a parsing-logic check plus manual verification against the shims `klc install`
writes.

## Acceptance coverage

### AC-1: metrics / reindex reach real handlers

| # | Test | How |
|---|------|-----|
| 1.1 | `klc metrics --rollup` not "not implemented" | run dispatcher; stderr must not contain "command not implemented" |
| 1.2 | `klc reindex` (no arg) prints usage, exit 2 | stderr contains "usage: klc reindex", not "not implemented" |
| 1.3 | `klc metrics` (no arg) prints usage, exit 2 | stderr contains "usage: klc metrics", not "not implemented" |

### AC-2: jira-sync dispatches to jira_sync_cmd

| # | Test | How |
|---|------|-----|
| 2.1 | `klc jira-sync` reaches wrapper | dispatcher run must not print "command not implemented"; jira_sync_cmd.run invoked |

### AC-3: resolveFrameworkRoot reads KLC_FW (TS)

| # | Test | How |
|---|------|-----|
| 3.1 | bash shim `KLC_FW="..."` parsed | regex/logic check against real `_shim_source` output |
| 3.2 | cmd shim `set "KLC_FW=..."` parsed | check against `_shim_source_cmd` output |
| 3.3 | ps1 shim `$env:KLC_FW = '...'` parsed | check against `_shim_source_ps1` output |
| 3.4 | legacy `KLC_FRAMEWORK_ROOT` / `$FW` still parsed | fallback branches retained |

### AC-4: build:work next-action names step card + required pick

| # | Test | How |
|---|------|-----|
| 4.1 | status.py at build:work names step card | seed meta impl_step=2 + `_prompt_step_2.md`; `_next_hint` mentions `_prompt_step_2.md` |
| 4.2 | status.py default step 1 | no impl_step → mentions `_prompt_step_1.md` |
| 4.3 | status.py names required single pick | build:work hint contains `--pick 1` |
| 4.4 | VS Code reader resolves step card + `--pick 1` | `buildTicketState`/`buildAckCommand` parse check |

## Edge cases

- `klc metrics`/`klc reindex`/`klc jira-sync` must remain in help text even
  though they are no longer routed via `_run_phase`.
- Non-build `:work` hint must still point at flat `<phase>/_prompt.md` (no
  regression from the build-specific branch).
- Phases with a single non-required pick, or multiple required picks, must keep
  their existing ack-command rendering (`--pick <N>` placeholder for >1).
- `jira` (distinct from `jira-sync`) must still route correctly.
- Legacy shims that still declare `KLC_FRAMEWORK_ROOT` must keep resolving.
