# Implementation plan — KLC-056

## step-1 — Define HolderConflictError and acquire_holder

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

## step-2 — Implement release_holder and no-op / conflict paths

**Goal:** Add `release_holder()` to `holder.py` so AC-4, AC-5, AC-6, and AC-7 pass.
**RED:** `tests/test_holder.py::test_release_by_holder_clears_field`, `tests/test_holder.py::test_release_refused_when_held_by_other`, `tests/test_holder.py::test_release_noop_when_null`, `tests/test_holder.py::test_no_direct_filesystem_io`
**GREEN:** Add `release_holder()` to `core/skills/holder.py` as shown in the code sketch.
**VERIFY:** `cd /home/ek/projects/klc && python -m pytest tests/test_holder.py -v`
**Expected:** `8 passed`
**COMMIT:** `KLC-056 step-2: add release_holder with clear/conflict/noop paths`
**Affected files:** `core/skills/holder.py`
**Interfaces:** `release_holder(ticket: str, identity: dict) -> bool`
**Depends on:** step-1
**Code sketch:**
```python
def release_holder(ticket: str, identity: dict) -> bool:
    """Clear holder if the caller owns it.
    Returns True if cleared, False if already null.
    Raises HolderConflictError if a different identity holds the phase."""
    _validate_identity(identity)
    meta = _lc.read_meta(ticket)
    existing = meta.get("holder")
    if not existing:
        return False  # AC-6: no-op
    if existing["id"] != identity["id"]:
        raise HolderConflictError(
            f"phase held by {existing['id']!r}; cannot release",
            existing,
        )
    meta["holder"] = None
    _lc.write_meta(ticket, meta)
    return True
```
