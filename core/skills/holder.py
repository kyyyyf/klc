#!/usr/bin/env python3
"""holder.py — phase-ownership primitive over meta.json (KLC-056).

A `holder` sub-object records who currently owns the ticket's active phase:

    meta["holder"] = {"id": <str>, "machine": <str>, "since": <ISO-8601 UTC Z>}

Two operations, both pure logic layered on top of lifecycle.read_meta /
lifecycle.write_meta — NO direct filesystem I/O and NO git operations here:

  acquire_holder(ticket, identity) -> dict
    First-grab claim. Absent/null holder → write and return the holder dict.
    Same id already holds → idempotent: return the existing dict WITHOUT
    refreshing `since`. Different id holds → raise HolderConflictError.

  release_holder(ticket, identity) -> bool
    Current holder releases → set holder=None, return True.
    Holder already null/absent → no-op, return False.
    Different id holds → raise HolderConflictError.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

# Import convention copied from gate_policy.py: put core/skills (this file's
# own directory) on sys.path with a presence guard, then `import lifecycle`
# and reach through the module (lifecycle.read_meta / lifecycle.write_meta) so
# callers and tests can monkeypatch those two functions.
_skills_dir = Path(__file__).resolve().parent
if str(_skills_dir) not in sys.path:
    sys.path.insert(0, str(_skills_dir))

import lifecycle  # noqa: E402


class HolderConflictError(RuntimeError):
    """Raised when a holder operation conflicts with a DIFFERENT holder.

    Carries the existing holder dict on `.holder` so callers can report the
    current owner's id and since.
    """

    def __init__(self, message: str, holder: dict | None = None):
        super().__init__(message)
        self.holder = holder


def _now() -> str:
    """ISO-8601 UTC timestamp ending in 'Z' (mirrors lifecycle._now)."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_identity(identity: dict) -> tuple[str, str]:
    """Return (id, machine) or raise ValueError if either is missing/empty."""
    if not isinstance(identity, dict):
        raise ValueError("identity must be a dict with 'id' and 'machine'")
    ident_id = identity.get("id")
    machine = identity.get("machine")
    if not ident_id or not isinstance(ident_id, str):
        raise ValueError("identity['id'] is required and must be a non-empty str")
    if not machine or not isinstance(machine, str):
        raise ValueError("identity['machine'] is required and must be a non-empty str")
    return ident_id, machine


def acquire_holder(ticket: str, identity: dict) -> dict:
    """Claim the current phase for `identity` (first-grab).

    - No holder (absent or null) → write {id, machine, since} and return it.
    - Same id already holds → idempotent: return existing WITHOUT touching since.
    - Different id already holds → raise HolderConflictError(holder=existing).
    """
    ident_id, machine = _validate_identity(identity)
    meta = lifecycle.read_meta(ticket)
    existing = meta.get("holder")
    if existing:
        if existing.get("id") == ident_id:
            # Idempotent re-acquire: preserve the original `since`.
            return existing
        raise HolderConflictError(
            f"ticket {ticket!r} already held by {existing.get('id')!r} "
            f"since {existing.get('since')!r}",
            holder=existing,
        )
    acquired = {"id": ident_id, "machine": machine, "since": _now()}
    meta["holder"] = acquired
    lifecycle.write_meta(ticket, meta)
    return acquired


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("holder.py is a library module; import it, don't run it")
