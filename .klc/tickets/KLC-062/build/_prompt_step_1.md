# Agent prompt — KLC-062 · build:work · step-1

Ticket: **KLC-062** · track: **M** · kind: **bug**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

- Make `klc remind` a genuinely side-effect-free advisory verb: running it must
  never mutate any ticket's `meta.json`, for ANY ticket in ANY phase, including
  a completable `discovery:work` ticket held by the caller. This is the
  invariant that justifies `remind` living in `NO_DRAIN_CMDS` and being wired
  into a hook that fires on every `UserPromptSubmit`.
- Restore the read-only contract of `klc status` (and the raw-read discipline
  `klc board` already follows): reading a ticket for display must not persist a
  legacy-phase migration back to disk.
- Preserve the existing functional behaviour of `risk_tags` — they must still be
  synced from `spec.md` into `meta.json` at the real completion transition (the
  `ack` path), so no real phase advance loses risk-tag data.
- Close the test gap that let this bug ship: add coverage that drives `remind`
  (and `status`) against write-capable and legacy-phase fixtures and asserts
  `meta.json` is byte-identical afterward.

## Acceptance Criteria

1. AC-1: `klc remind` never writes `meta.json` for ANY ticket/phase — including a
   completable `discovery:work` ticket held by the caller: meta.json byte-identical
   before/after.
2. AC-2: `klc status` and `klc remind` never persist a legacy-phase migration (no
   read_meta write-back on read); status's read-only contract holds. (Align with
   board.py's raw json.loads or a read-only read variant.)
3. AC-3: `risk_tags` are still persisted at the correct time (the `ack`/completion
   path) — no functional regression to risk-tag behavior for real phase transitions.
4. AC-4 (test plan): add a `discovery:work`-completable fixture asserting
   `meta.json` byte-identical after `klc remind` (mirror the existing
   `test_*_does_not_write_meta` pattern used for board/status); add a legacy-phase
   fixture asserting `status`/`remind` don't rewrite it.
5. AC-5: exit-0/no-crash contract + `NO_DRAIN_CMDS` (remind excluded from Jira
   drain) preserved.

### Current step — step-1

**non-persisting meta read: read_meta_ro + status wiring**

**Goal:** Add `lifecycle.read_meta(ticket, *, persist_migration: bool = True)` and
a thin `lifecycle.read_meta_ro(ticket)` wrapper, then switch `status._meta` to the
read-only variant. The legacy migration still runs in-memory (display stays
correct) but is no longer written back to disk on a read (AC-2). Closes the
`status` read-only contract violation.

**RED:** `tests/integration/test_status_holder.py::test_status_does_not_write_meta_legacy_phase`
— fabricate a ticket with a legacy `meta.json:phase` (e.g. `design-pending`),
snapshot `meta.json` bytes, run `klc status`; asserts exit 0, the migrated phase
shows in output, and `meta.json` is byte-identical. Fails today because
`read_meta` write-backs the migration.

**GREEN:** Thread `persist_migration` into `read_meta`: only call `write_meta`
when `_migrate_legacy_phase(meta)` AND `persist_migration`. Add
`read_meta_ro(ticket)` → `read_meta(ticket, persist_migration=False)`. Point
`status._meta` at `read_meta_ro`.

**Interfaces:**
```python
def read_meta(ticket: str, *, persist_migration: bool = True) -> dict: ...
def read_meta_ro(ticket: str) -> dict: ...
```

**Expected:** `1 passed` for the new test; existing `test_status_holder.py` and
`test_board_holder.py` stay green.

**VERIFY:** `cd "$PROJECT_ROOT" && python -m pytest tests/integration/test_status_holder.py -x -q`

**COMMIT:** `KLC-062 step-1: read_meta_ro suppresses legacy-migration write-back; status uses it`

**Affected:** `core/skills/lifecycle.py`, `core/phases/status.py`,
`tests/integration/test_status_holder.py`.

**Code sketch:**
```python
# lifecycle.py
def read_meta(ticket, *, persist_migration=True):
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        raise FileNotFoundError(...)
    meta = json.loads(p.read_text(encoding="utf-8"))
    if _migrate_legacy_phase(meta) and persist_migration:
        write_meta(ticket, meta)
    return meta

def read_meta_ro(ticket):
    return read_meta(ticket, persist_migration=False)
```

**Depends-on:** none

**Affected files**:


**Expected tests**:



### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.

### Failing test(s) to make green

`# run the failing test added by the test agent`

Run with: `# see test-framework.json`

---

## Role prompt


**Before acting, read the role prompt at:**

```
/home/ek/projects/klc/.claude/worktrees/agent-a0be661c40fe49a8b/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-062 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-062/impl-plan.md`
- Full spec: `.klc/tickets/KLC-062/spec.md`
- Full test-plan: `.klc/tickets/KLC-062/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-062 step-1` and
run `klc step KLC-062 2` to get the next step's card,
or `klc ack KLC-062 --pick 1` if this was the last step.
