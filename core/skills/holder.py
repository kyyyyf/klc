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
import math as _math
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


class HolderActiveError(HolderConflictError):
    """Raised by steal_holder when the current holder is still ACTIVE.

    "Active" means its liveness timestamp (heartbeat_at, else since) is within
    the configured TTL, so a takeover is refused. Carries `.holder` (the live
    owner) and `.age_seconds` (measured staleness) for the caller's message.
    """

    def __init__(self, message: str, holder: dict | None = None,
                 age_seconds: float | None = None):
        super().__init__(message, holder=holder)
        self.age_seconds = age_seconds


# Default staleness window: a holder whose heartbeat_at (else since) is older
# than this is considered abandoned and may be stolen. 30 minutes. There is no
# natural config home for this (config/*.yml carry no lifecycle-lock knobs), so
# it lives as a module constant; the CLI exposes --ttl-minutes to override.
HOLDER_TTL_SECONDS = 30 * 60


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


def _existing_holder(meta: dict) -> dict | None:
    """Read and fail-close on a MALFORMED stored holder.

    A free phase is ONLY an absent or explicitly-null `holder`. Any other
    value (empty dict, non-dict, or a dict missing/empty id/machine/since) is
    a corrupt record: raise ValueError rather than silently overwriting it
    (empty-dict was previously falsy → treated as free) or returning it as a
    valid idempotent acquire (same-id record missing `machine`).
    """
    existing = meta.get("holder")
    if existing is None:
        return None
    if not isinstance(existing, dict):
        raise ValueError(f"meta.holder is malformed (not a dict): {existing!r}")
    for key in ("id", "machine", "since"):
        val = existing.get(key)
        if not val or not isinstance(val, str):
            raise ValueError(
                f"meta.holder is malformed: {key!r} missing or not a non-empty str"
            )
    return existing


def acquire_holder(ticket: str, identity: dict) -> dict:
    """Claim the current phase for `identity` (first-grab).

    - No holder (absent or null) → write {id, machine, since} and return it.
    - Same id already holds → idempotent: return existing WITHOUT touching since.
    - Different id already holds → raise HolderConflictError(holder=existing).
    """
    ident_id, machine = _validate_identity(identity)
    meta = lifecycle.read_meta(ticket)
    existing = _existing_holder(meta)
    if existing is not None:
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


def release_holder(ticket: str, identity: dict) -> bool:
    """Release the current phase's holder on behalf of `identity`.

    - No holder (absent or null) → no-op, return False.
    - Different id holds → raise HolderConflictError(holder=existing); the
      holder is left unchanged.
    - Caller is the current holder → set holder=None, return True.
    """
    ident_id, _machine = _validate_identity(identity)
    meta = lifecycle.read_meta(ticket)
    existing = _existing_holder(meta)
    if existing is None:
        return False
    if existing.get("id") != ident_id:
        raise HolderConflictError(
            f"ticket {ticket!r} held by {existing.get('id')!r}; "
            f"cannot be released by {ident_id!r}",
            holder=existing,
        )
    meta["holder"] = None
    lifecycle.write_meta(ticket, meta)
    return True


def heartbeat_holder(ticket: str) -> dict:
    """Refresh the active holder's liveness timestamp (KLC-058).

    Sets `holder.heartbeat_at` to the current UTC timestamp and leaves every
    other field (id, machine, since, ...) untouched. Returns the updated
    holder dict.

    Raises ValueError when there is no holder to heartbeat (absent or null).
    A malformed holder record still fails closed via _existing_holder.
    """
    meta = lifecycle.read_meta(ticket)
    existing = _existing_holder(meta)
    if existing is None:
        raise ValueError(
            f"ticket {ticket!r} has no holder to heartbeat; "
            f"acquire the holder first"
        )
    # Mutate in place: id/machine/since and any sibling fields are preserved.
    existing["heartbeat_at"] = _now()
    meta["holder"] = existing
    lifecycle.write_meta(ticket, meta)
    return existing


def _parse_iso_z(ts) -> _dt.datetime:
    """Parse an ISO-8601 UTC 'Z' timestamp into an aware datetime.

    Raises ValueError on any non-string or malformed value (never an
    AttributeError from calling .replace on a non-str), so callers can treat a
    single `except ValueError` as "this stamp is unusable".
    """
    if not isinstance(ts, str):
        raise ValueError(f"timestamp must be a str, got {type(ts).__name__}: {ts!r}")
    parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def _holder_age_seconds(existing: dict) -> float:
    """Seconds since the holder was last known alive.

    Liveness is `heartbeat_at` when it is a parseable ISO-Z string, else the
    acquire time `since`. A missing / non-string / malformed heartbeat_at must
    NOT crash and must NOT make a genuinely-stale holder un-stealable: it falls
    back to `since`. If `since` is also unusable, raise a clear ValueError so
    the CLI maps it to a clean non-zero exit rather than a traceback.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    for ref in (existing.get("heartbeat_at"), existing.get("since")):
        try:
            return (now - _parse_iso_z(ref)).total_seconds()
        except ValueError:
            continue
    raise ValueError(
        "holder liveness is unusable: neither 'heartbeat_at' nor 'since' is a "
        "parseable ISO-8601 UTC timestamp"
    )


def steal_holder(ticket: str, identity: dict,
                 ttl_seconds: float = HOLDER_TTL_SECONDS,
                 on_takeover=None) -> dict:
    """Take over the holder slot for `identity` — ONLY if the current holder
    is stale (KLC-058).

    - No holder (absent or null) → ValueError (nothing to steal; use acquire).
    - Current holder age (from heartbeat_at, else since) < ttl_seconds →
      HolderActiveError; the holder is left unchanged.
    - Current holder age >= ttl_seconds → overwrite with a fresh
      {id, machine, since} holder. If `on_takeover` is given it is called with
      (previous_holder, age_seconds) BEFORE the write, so a caller can warn
      before the takeover happens.

    Returns {"holder": <new>, "previous": <old>, "age_seconds": <float>}.
    """
    # Defense-in-depth (independent of the CLI's --ttl-minutes guard): a TTL
    # that is not a positive finite number would make the staleness gate
    # (age < ttl_seconds) misbehave — <=0 or NaN never holds, so a FRESH holder
    # would be overwritten; inf would make nothing ever stealable. Reject up
    # front, before reading identity/holder, so a bad TTL can never mutate state.
    if (not isinstance(ttl_seconds, (int, float)) or isinstance(ttl_seconds, bool)
            or not _math.isfinite(ttl_seconds) or ttl_seconds <= 0):
        raise ValueError(
            f"ttl_seconds must be a positive finite number, got {ttl_seconds!r}"
        )
    ident_id, machine = _validate_identity(identity)
    meta = lifecycle.read_meta(ticket)
    existing = _existing_holder(meta)
    if existing is None:
        raise ValueError(
            f"ticket {ticket!r} has no holder to steal; use acquire_holder"
        )
    age = _holder_age_seconds(existing)
    if age < ttl_seconds:
        raise HolderActiveError(
            f"ticket {ticket!r} still actively held by {existing.get('id')!r} "
            f"(idle {int(age)}s < TTL {int(ttl_seconds)}s); refusing to steal",
            holder=existing,
            age_seconds=age,
        )
    if on_takeover is not None:
        on_takeover(existing, age)
    stolen = {"id": ident_id, "machine": machine, "since": _now()}
    meta["holder"] = stolen
    lifecycle.write_meta(ticket, meta)
    return {"holder": stolen, "previous": existing, "age_seconds": age}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("holder.py is a library module; import it, don't run it")
