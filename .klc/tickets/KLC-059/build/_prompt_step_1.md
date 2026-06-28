# Agent prompt — KLC-059 · build:work · step-1

Ticket: **KLC-059** · track: **S** · kind: **unknown**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Add `klc remind` — a silent-by-default CLI verb that emits one reminder line when the current git identity holds a ticket phase in `:work` state and `phase_completion.can_complete` returns True, delivered automatically via a Claude Code UserPromptSubmit hook.

## Acceptance Criteria

- [ ] AC-1: `klc remind` with no completable-held ticket produces no output and exits 0.
- [ ] AC-2: `klc remind` with a ticket where the current git identity is the `holder` AND `phase_completion.can_complete(ticket, phase) == True` AND the phase state is `:work` emits exactly one line of the form `KLC-xxx <phase> is done — run klc ack` and exits 0.
- [ ] AC-3: `klc remind` does not fire for tickets held by a different git identity (i.e. holder.id != current git user.email); those are silently skipped.
- [ ] AC-4: A `UserPromptSubmit` hook entry in `klc-plugin/hooks/hooks.json` invokes `klc remind`; the hook exits 0 (non-blocking) in all cases, including when `klc remind` cannot locate a ticket.
- [ ] AC-5: An optional statusline mode (`klc remind --statusline`) emits the same reminder line to stdout for use in shell prompts; no output when nothing to do.

### Current step — step-1

**Add `klc remind` core logic as `remind.py`**

**Goal:** Implement the `klc remind` verb as `core/phases/remind.py` with a `run(argv)` entry point; reads all tickets in `.klc/tickets/`, checks holder identity against current git user, calls `phase_completion.can_complete`, emits one line per completable-held ticket in `:work` state.
**RED:** `tests/integration/test_remind.py::test_remind_silent_when_nothing_to_do`, `tests/integration/test_remind.py::test_remind_fires_when_held_and_completable`, `tests/integration/test_remind.py::test_remind_silent_for_other_holder`
**GREEN:** Create `core/phases/remind.py` with `run(argv)` that implements the three behaviours; add `remind` to `LIFECYCLE_CMDS` in `scripts/klc`.
**VERIFY:** `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_remind.py -k "silent_when_nothing or fires_when or silent_for_other" -v`
**Expected:** `3 passed`
**COMMIT:** `KLC-059 step-1: add klc remind core logic`
**Affected files:** `core/phases/remind.py`, `scripts/klc`
**Interfaces:** `run(argv: list[str]) -> int` — exits 0 always; `--statusline` flag supported
**Depends on:** none
**Code sketch:**
```python
# core/phases/remind.py
import os, subprocess, sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
import phase_completion as _pc
from _paths import klc_tickets_dir

def _git_user() -> str:
    for key in ("user.email", "user.name"):
        try:
            r = subprocess.run(["git", "config", "--get", key],
                               capture_output=True, text=True, timeout=5)
            if r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return os.environ.get("USER", "unknown")

def run(argv: list[str]) -> int:
    identity = _git_user()
    tickets_dir = klc_tickets_dir()
    if not tickets_dir.exists():
        return 0
    import lifecycle as _lc, phases as _ph
    for tdir in sorted(tickets_dir.iterdir()):
        if not (tdir / "meta.json").exists():
            continue
        try:
            meta = _lc.read_meta(tdir.name)
        except Exception:
            continue
        holder = meta.get("holder") or {}
        if holder.get("id") != identity:
            continue
        phase_val = meta.get("phase", "")
        if not phase_val.endswith(":work"):
            continue
        phase_id = phase_val.split(":")[0]
        try:
            ok, _ = _pc.can_complete(tdir.name, phase_id)
        except Exception:
            continue
        if ok:
            print(f"{tdir.name} {phase_id} is done — run klc ack")
    return 0
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
/home/ek/projects/klc/core/agents/impl.md
```

The role prompt contains LSP usage rules, output format, and signal
conventions required for this phase. If you cannot access the file,
re-run `klc step KLC-059 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-059/impl-plan.md`
- Full spec: `.klc/tickets/KLC-059/spec.md`
- Full test-plan: `.klc/tickets/KLC-059/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-059 step-1` and
run `klc step KLC-059 2` to get the next step's card,
or `klc ack KLC-059 --pick 1` if this was the last step.
