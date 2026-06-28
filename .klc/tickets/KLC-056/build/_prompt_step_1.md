# Agent prompt — KLC-056 · build:work · step-1

Ticket: **KLC-056** · track: **S** · kind: **unknown**

You are in the **Build** phase, TDD loop. Your job: make the failing
test(s) for **step-1** pass. Read the role prompt below, then
produce the outputs listed at the bottom.

---

## Context (minimal — load more via LSP on demand)

### Goals + Acceptance Criteria (from spec.md)

## Goals

Add a `holder` sub-object to `meta.json` on the current phase so that `acquire_holder()` claims a free phase (first-grab semantics) and `release_holder()` clears it, giving the multi-user coordination layer a pure-logic, git-transaction-free ownership primitive.

## Acceptance Criteria

- [ ] AC-1: `acquire_holder(ticket, identity)` writes `meta.holder = {id, machine, since}` when `meta.holder` is absent or null, and returns the holder dict.
- [ ] AC-2: `acquire_holder(ticket, identity)` raises `HolderConflictError` (with the existing holder's id and since in the exception) when `meta.holder` is already set to a different identity id.
- [ ] AC-3: `acquire_holder(ticket, identity)` is idempotent: if the caller already holds the phase (same id), it returns the existing holder dict without overwriting `since`.
- [ ] AC-4: `release_holder(ticket, identity)` sets `meta.holder` to null when the caller is the current holder, and returns True.
- [ ] AC-5: `release_holder(ticket, identity)` raises `HolderConflictError` when a different identity holds the phase, and leaves `meta.holder` unchanged.
- [ ] AC-6: `release_holder(ticket, identity)` is a no-op (returns False) when `meta.holder` is already null.
- [ ] AC-7: Both functions depend solely on `lifecycle.read_meta` / `lifecycle.write_meta` — no direct filesystem I/O and no git operations are performed inside `holder.py`.
- [ ] AC-8: `identity` parameter is a dict with at least `{id: str, machine: str}`; `since` in the stored holder is an ISO-8601 UTC timestamp set at acquire time.

### Current step — step-1

**Define HolderConflictError and acquire_holder**

**Goal:** Create `core/skills/holder.py` with `HolderConflictError`, `acquire_holder()`, and the idempotent same-owner path so AC-1, AC-2, AC-3, and AC-8 pass.
**RED:** `tests/test_holder.py::test_acquire_on_free_phase`, `tests/test_holder.py::test_acquire_refused_when_held_by_other`, `tests/test_holder.py::test_acquire_idempotent_same_holder`, `tests/test_holder.py::test_identity_shape_and_since_format`
**GREEN:** Write `core/skills/holder.py` with the acquire logic shown in the code sketch.
**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_holder.py::test_acquire_on_free_phase tests/test_holder.py::test_acquire_refused_when_held_by_other tests/test_holder.py::test_acquire_idempotent_same_holder tests/test_holder.py::test_identity_shape_and_since_format -v`
**Expected:** `4 passed`
**COMMIT:** `KLC-056 step-1: add acquire_holder with first-grab and idempotent semantics`
**Affected files:** `core/skills/holder.py` (new), `tests/test_holder.py` (new)
**Interfaces:** `acquire_holder(ticket: str, identity: dict) -> dict`, `class HolderConflictError(RuntimeError)`
**Depends on:** none
**Code sketch:**
```python
# core/skills/holder.py
from __future__ import annotations
import datetime as _dt
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
import lifecycle as _lc  # noqa: E402


class HolderConflictError(RuntimeError):
    """Raised when a different identity already holds the phase."""
    def __init__(self, msg: str, holder: dict):
        super().__init__(msg)
        self.holder = holder


def _now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_identity(identity: dict) -> None:
    if not identity.get("id"):
        raise ValueError("identity.id must be a non-empty string")
    if not identity.get("machine"):
        raise ValueError("identity.machine must be a non-empty string")


def acquire_holder(ticket: str, identity: dict) -> dict:
    """First-grab: claim the current phase if free; idempotent if already owned.
    Raises HolderConflictError if a different identity holds it."""
    _validate_identity(identity)
    meta = _lc.read_meta(ticket)
    existing = meta.get("holder")
    if existing:
        if existing["id"] == identity["id"]:
            return existing  # idempotent — same holder, return as-is
        raise HolderConflictError(
            f"phase held by {existing['id']!r} since {existing['since']!r}",
            existing,
        )
    holder = {"id": identity["id"], "machine": identity["machine"], "since": _now_utc()}
    meta["holder"] = holder
    _lc.write_meta(ticket, meta)
    return holder
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
re-run `klc step KLC-056 1` with `KLC_CARD_INLINE=1` to
embed it directly in the card.


---

## Navigation

- Full impl-plan: `.klc/tickets/KLC-056/impl-plan.md`
- Full spec: `.klc/tickets/KLC-056/spec.md`
- Full test-plan: `.klc/tickets/KLC-056/test-plan.md`
- Module index: `.klc/index/modules.json`
- Symbols: `.klc/index/symbols_by_module.json`

Use LSP (`goToDefinition`, `findReferences`, `hover`, `workspaceSymbol`)
for any symbol navigation — do not open full source files unless
LSP is insufficient.

---

## When done

After tests are green, emit `IMPL_STEP_OK KLC-056 step-1` and
run `klc step KLC-056 2` to get the next step's card,
or `klc ack KLC-056 --pick 1` if this was the last step.
