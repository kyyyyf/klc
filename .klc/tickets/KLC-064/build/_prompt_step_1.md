# Agent prompt — KLC-064 · build:work · step-1

Ticket: **KLC-064** · track: **S** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Give `heartbeat_holder` a real production caller so an actively-held ticket's
`heartbeat_at` advances while work is in progress, closing the wiring gap where
staleness was always measured from `since` (acquire time) and a live holder on a
long phase became stealable while still working.

## Acceptance Criteria

- [ ] AC-1: A new `klc heartbeat` verb, wired to a non-blocking `UserPromptSubmit`
  hook, calls `holder.heartbeat_holder` for every ticket the current git identity
  holds in a `<phase>:work` state, so `heartbeat_at` is written/advanced on an
  actively-held ticket. (Tickets held by another identity, or not in `:work`, are
  left untouched — mirrors `klc remind`.)
- [ ] AC-2: After a heartbeat, a ticket whose `since` is older than
  `HOLDER_TTL_SECONDS` is NOT stealable — `steal_holder` raises `HolderActiveError`
  because staleness is measured from the fresh `heartbeat_at`, not from `since`;
  once `heartbeat_at` is older than the TTL (heartbeat silence) the steal succeeds.
- [ ] AC-3: An e2e test proves `heartbeat_at` advances during a simulated long hold,
  that a steal is refused while the heartbeat is fresh, and that the same steal is
  allowed after a full TTL of heartbeat silence.
- [ ] AC-4: Feature-OFF parity — `klc heartbeat` and its hook are best-effort: they
  perform no git operations, always exit 0, and swallow every error (missing
  identity, unreadable/corrupt meta, absent holder) so they never crash or block the
  surrounding phase/prompt, matching the `klc remind` advisory contract.

### Current step — step-1

**`klc heartbeat` command: refresh heartbeat_at for identity-held :work tickets**

**Goal:** Add a `klc heartbeat` verb that scans tickets the current git identity
holds in a `<phase>:work` state and calls `holder.heartbeat_holder` on each,
best-effort and always exit 0 (mirrors `klc remind`). Register it in
`scripts/klc` so it dispatches and skips the Jira drain. This is the real
production caller that AC-1/AC-2 require.
**RED:** `tests/integration/test_heartbeat.py::test_heartbeat_writes_heartbeat_at_on_held_work_ticket` and `::test_fresh_heartbeat_blocks_steal_despite_old_since` — fail because `core/phases/heartbeat.py` does not exist and `heartbeat` is not a known command.
**GREEN:** Create `core/phases/heartbeat.py` with `run(argv)` that chdirs into `project_root()`, resolves the identity non-raising (same order as `remind._git_user`), iterates `klc_tickets_dir()`, and for each ticket held by that identity in a `:work` phase calls `holder.heartbeat_holder(ticket)` inside a `try/except Exception: continue`. Add `"heartbeat"` to `LIFECYCLE_CMDS` and to `NO_DRAIN_CMDS` in `scripts/klc`.
**VERIFY:** `PROJECT_ROOT="$(git rev-parse --show-toplevel)" python3 -m pytest tests/integration/test_heartbeat.py -k "writes_heartbeat_at or blocks_steal" -q`
**Expected:** `2 passed`
**COMMIT:** `KLC-064 step-1: klc heartbeat refreshes held :work tickets`
**Affected files:** `core/phases/heartbeat.py`, `scripts/klc`, `tests/integration/test_heartbeat.py`
**Interfaces:** `heartbeat.run(argv: list[str]) -> int` (always 0); no change to `holder.heartbeat_holder`.
**Depends on:** none
**Code sketch:**
```python
# core/phases/heartbeat.py  (mirrors remind.py structure)
import holder, lifecycle as _lc
from _paths import klc_tickets_dir, project_root

def run(argv: list[str]) -> int:
    prev = os.getcwd()
    try:
        os.chdir(project_root())
    except Exception:
        return 0
    try:
        identity = _git_user()            # non-raising, same as remind
        tdir_root = klc_tickets_dir()
        if not tdir_root.exists():
            return 0
        for tdir in sorted(tdir_root.iterdir()):
            if not (tdir / "meta.json").exists():
                continue
            ticket = tdir.name
            try:
                meta = _lc.read_meta(ticket)
                h = meta.get("holder")
                phase = meta.get("phase", "")
                if (isinstance(h, dict) and h.get("id") == identity
                        and isinstance(phase, str) and phase.endswith(":work")):
                    holder.heartbeat_holder(ticket)   # writes heartbeat_at
            except Exception:
                continue      # advisory: one bad ticket never aborts the rest
        return 0
    finally:
        try: os.chdir(prev)
        except Exception: pass
```

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
/home/ek/projects/klc/.claude/worktrees/agent-a3b8527058e430c61/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-064 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-064/impl-plan.md`
- Full spec: `.klc/tickets/KLC-064/spec.md`
- Full test-plan: `.klc/tickets/KLC-064/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-064 step-1` and
run `klc step KLC-064 2` to get the next step's card,
or `klc ack KLC-064 --pick 1` if this was the last step.
