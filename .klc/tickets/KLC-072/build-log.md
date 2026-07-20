---
ticket: KLC-072
kind: bug
authority: agent
---

# KLC-072 — build log

TDD build of the four dispatch fixes. Approach: verify each bug against current
code, write failing tests (RED), implement, confirm GREEN, then full regression.

## Reproduction (all four verified on this branch before any change)

- `klc metrics --rollup` / `klc reindex` → `klc: command not implemented`
  (both shadowed by the generic `_run_phase` route via `OPERATIONAL_CMDS`).
- `klc jira-sync` → `klc: command not implemented` (routed to
  `core/phases/jira_sync.py`, which does not exist; wrapper is
  `jira_sync_cmd.py`).
- `status.py` at `build:work` (impl_step=2, `_prompt_step_2.md` present) →
  `→ build:work. Run \`klc ack KLC-900\` when done` — missed the per-step card
  and omitted the required `--pick 1`.
- `vscode-extension/src/klcReader.ts` `resolveFrameworkRoot` parsed
  `KLC_FRAMEWORK_ROOT` / `$FW`; the installed shims declare `KLC_FW`.

## RED

`tests/integration/test_klc072_dispatch.py` — 14 tests. Initial run:
`10 failed, 4 passed` (the 4 pre-passing are the shim-parity regex checks that
document the target property and the already-correct non-build flat-card hint).

## Changes (GREEN)

- **step-1 — `scripts/klc`**: dropped `metrics`, `reindex`, `jira-sync` from
  `OPERATIONAL_CMDS` (none has a phase file), and added an explicit `jira-sync`
  branch routing to `_run_phase("jira_sync_cmd", rest)`. Explicit
  `metrics`/`reindex` handlers are now reachable.
- **step-2 — `core/phases/status.py`**: `_next_hint` now resolves the build
  per-step card via `_work_card` (`build/_prompt_step_<impl_step>.md`, default 1)
  and names the required single pick via `_ack_command`
  (`klc ack <ticket> --pick 1`).
- **step-3 — `vscode-extension/src/klcReader.ts`**: `resolveFrameworkRoot` reads
  `KLC_FW` (primary; covers all three shim flavours) with the legacy
  `KLC_FRAMEWORK_ROOT` / `$FW` forms kept as fallback; `readMeta`/`liveTickets`
  surface `impl_step`; `buildTicketState` passes the build step into
  `promptCardPath`.
- **step-4 — `vscode-extension/src/treeProvider.ts`**: `buildAckCommand` emits
  `--pick <id>` when the phase requires exactly one pick.

Final: `14 passed`.

## Verification

- CLI: `klc metrics --rollup` → JSON rollup (rc 0); `klc reindex` →
  `usage: klc reindex <ticket>` (rc 2); `klc jira-sync status` →
  `queue: 0 pending` (rc 0); `klc jira` unaffected.
- Live: `klc status KLC-072` at `build:work` now prints
  `cat .../build/_prompt_step_1.md` and `When done: klc ack KLC-072 --pick 1`.
- TS: `npm install` + `npx tsc -p ./ --noEmit` → rc 0 (no test harness in the
  extension; the reader/tree logic is additionally asserted by the Python
  shim-parity + source-guard tests).
- Full regression: `python3 -m pytest tests/ -q --ignore=tests/fixtures` →
  `1038 passed, 13 skipped`.
