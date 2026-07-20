---
ticket: KLC-072
kind: bug
authority: agent
---

# KLC-072 — implementation plan

Four targeted fixes, TDD (RED first) where the surface is Python. The VS Code
`.ts` fixes have no extension test harness, so they are verified by parsing-logic
assertions in a Python test plus manual checks against the installed shims.

## step-1 — scripts/klc: reach metrics/reindex/jira-sync handlers

**Goal**: `klc metrics`, `klc reindex`, and `klc jira-sync` reach their real
handlers instead of printing "command not implemented".

**Affected**: scripts/klc

**Interfaces**: `_dispatch(argv)` in scripts/klc; new explicit `jira-sync`
branch routing to `core/phases/jira_sync_cmd.py` via `_run_phase("jira_sync_cmd",
rest)`. Remove `metrics`, `reindex`, `jira-sync` from the `OPERATIONAL_CMDS`
tuple so the generic phase route no longer shadows them.

**Expected**: dispatcher stderr never contains "command not implemented" for
these three verbs; no-arg `metrics`/`reindex` still print their usage and exit 2.

**Code sketch**:

```python
OPERATIONAL_CMDS = ("board", "doctor", "install", "jira", "setup", "state")
# ...
if cmd == "jira-sync":
    return _run_phase("jira_sync_cmd", rest)
```

**VERIFY**: `python3 -m pytest tests/integration/test_klc072_dispatch.py -q`

**COMMIT**: `KLC-072 step-1: reachable metrics/reindex/jira-sync dispatch`

## step-2 — status.py: build:work step card + required pick

**Goal**: at `build:work`, the "next action" names the current per-step card
`build/_prompt_step_<impl_step>.md` (default 1) and the required single pick
`klc ack <ticket> --pick 1`.

**Affected**: core/phases/status.py

**Interfaces**: `_next_hint(ticket, cur_pid, cur_state, meta)`; a small
`_ack_command(ticket, pid)` helper that appends `--pick <id>` when the phase's
ack requires exactly one pick.

**Expected**: build:work hint mentions `_prompt_step_2.md` when `impl_step=2`,
`_prompt_step_1.md` by default, and contains `--pick 1`; non-build `:work` still
points at flat `<phase>/_prompt.md`.

**Code sketch**:

```python
if cur_pid == "build":
    step = meta.get("impl_step") or 1
    card = tdir / "build" / f"_prompt_step_{step}.md"
else:
    card = tdir / cur_pid / "_prompt.md"
```

**VERIFY**: `python3 -m pytest tests/integration/test_klc072_dispatch.py -q`

**COMMIT**: `KLC-072 step-2: build:work next-action names step card + pick`

## step-3 — klcReader.ts: KLC_FW + per-step build card

**Goal**: `resolveFrameworkRoot` reads the installed shim's `KLC_FW` variable;
`buildTicketState` resolves the per-step build card.

**Affected**: vscode-extension/src/klcReader.ts

**Interfaces**: `resolveFrameworkRoot(workspaceRoot, shimPath)` gains a `KLC_FW`
regex (primary), keeping legacy patterns as fallback; `readMeta` surfaces
`impl_step`; `buildTicketState` passes the build step into `promptCardPath`.

**Expected**: parsing the three shim forms yields the framework path; build:work
resolves `_prompt_step_<step>.md`.

**Code sketch**:

```typescript
let m = text.match(/KLC_FW\s*=\s*["']?([^"'\n]+)["']?/);
if (m) return m[1].trim();
```

**VERIFY**: `cd vscode-extension && npx tsc -p ./ --noEmit` plus the Python
shim-parity assertions in the KLC-072 test.

**COMMIT**: `KLC-072 step-3: vscode reader reads KLC_FW + per-step card`

## step-4 — treeProvider.ts: required single pick in ack command

**Goal**: `buildAckCommand` emits `--pick <id>` when the phase requires exactly
one pick (build's `1=approve`).

**Affected**: vscode-extension/src/treeProvider.ts

**Interfaces**: `buildAckCommand(workspaceRoot, ts)`.

**Expected**: at build:ack-needed the rendered command is
`<shim> ack <ticket> --pick 1`; multi-pick phases keep `--pick <N>`.

**Code sketch**:

```typescript
if (ts.phase.picks.length === 1) return `${base} --pick ${ts.phase.picks[0].id}`;
```

**VERIFY**: `cd vscode-extension && npx tsc -p ./ --noEmit`

**COMMIT**: `KLC-072 step-4: vscode ack command includes required single pick`
