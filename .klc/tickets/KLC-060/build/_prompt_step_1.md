# Agent prompt — KLC-060 · build:work · step-1

Ticket: **KLC-060** · track: **M** · kind: **feature**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Make the current-phase **holder** visible in the two read surfaces a user
checks first — `klc board` (cross-ticket kanban) and `klc status <ticket>`
(per-ticket path) — and add a "waiting on ack from `<id>`" hint when a ticket
sits in `ack-needed`. Purely derived from `meta.json`; no new persisted state,
no writes, no git, no forge API.

## Acceptance Criteria

1. AC-1: Given a ticket whose `meta.json` carries a current-phase `holder` with
   an `id`, when the user runs `klc board` (text and `--json`), then that
   ticket's row/record surfaces the holder id; given a ticket with **no**
   holder, the row renders unchanged from today (no crash, no empty artifact).
2. AC-2: Given a ticket in `ack-needed` whose current phase has a `holder`,
   when the user runs `klc status <ticket>`, then the current-phase annotation
   includes `waiting on ack from <id>`; given any other state, the holder (when
   present) is shown but the "waiting on ack" wording is omitted.
3. AC-3: Both commands are strictly read-only — they read `meta.json` and write
   nothing; a missing/null `holder` is tolerated everywhere (no `KeyError`,
   `--json` stays valid JSON).

### Current step — step-1

**Add holder_display helper with null-tolerant formatters**

**Goal:** Add a pure helper `core/skills/holder_display.py` that formats the
holder id and the waiting-on-ack hint from a `meta` dict, returning `None` for
every degraded shape (no holder, no id, empty id).

**RED:** Write `tests/integration/test_holder_display.py` asserting
`holder_label` and `waiting_hint` over the full shape matrix. Covers test-plan
edge cases: holder present with id, holder key present but `id` missing/null,
empty-string id treated as absent, and `waiting_hint` returning a string only
when `state == "ack-needed"` with an id (negative + fail-closed coverage for
AC-3 / C-002).

**Interfaces:**
- `holder_display.holder_label(meta: dict) -> str | None`
- `holder_display.waiting_hint(meta: dict, state: str) -> str | None`

**Expected:** `pytest` reports the new tests fail before GREEN (ImportError /
assertion), then `10 passed` after GREEN (exact count may differ as rows are
added; all asserted rows pass).

**VERIFY:** `python3 -m pytest tests/integration/test_holder_display.py -q`

**COMMIT:** `KLC-060 step-1: holder_display helper with null-tolerant formatters`

**Affected:**
- `core/skills/holder_display.py` (new)
- `tests/integration/test_holder_display.py` (new)

**Code sketch:**
```python
# core/skills/holder_display.py
from __future__ import annotations

STATE_ACK_NEEDED = "ack-needed"


def _holder_id(meta: dict) -> str | None:
    holder = (meta or {}).get("holder")
    if not isinstance(holder, dict):
        return None
    hid = holder.get("id")
    if not isinstance(hid, str) or not hid.strip():
        return None
    return hid


def holder_label(meta: dict) -> str | None:
    """Holder id for the current phase, or None when absent/degraded."""
    return _holder_id(meta)


def waiting_hint(meta: dict, state: str) -> str | None:
    """`waiting on ack from <id>` only in ack-needed with a holder id."""
    if state != STATE_ACK_NEEDED:
        return None
    hid = _holder_id(meta)
    return f"waiting on ack from {hid}" if hid else None
```

**Depends-on:** none

---

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
re-run `klc step KLC-060 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-060/impl-plan.md`
- Full spec: `.klc/tickets/KLC-060/spec.md`
- Full test-plan: `.klc/tickets/KLC-060/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-060 step-1` and
run `klc step KLC-060 2` to get the next step's card,
or `klc ack KLC-060 --pick 1` if this was the last step.
