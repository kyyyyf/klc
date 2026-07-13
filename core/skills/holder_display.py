#!/usr/bin/env python3
"""holder_display.py — read-only formatters for the current-phase holder (KLC-060).

Shared by `klc board` and `klc status` to surface who owns a ticket's active
phase without duplicating the null-tolerance rules. The `holder` sub-object is
written by holder.py (KLC-056) as `{id, machine, since}`; here we only read it.

Fail-closed contract: every degraded shape (absent holder, null holder, holder
that is not a dict, missing/null/empty/whitespace id) yields None — never an
exception — so a corrupt meta cannot crash a display command.
"""
from __future__ import annotations

STATE_ACK_NEEDED = "ack-needed"


def _holder_id(meta: dict) -> str | None:
    """Return a non-empty holder id string, or None for any degraded shape."""
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
    """`waiting on ack from <id>` only in ack-needed with a valid holder id."""
    if state != STATE_ACK_NEEDED:
        return None
    hid = _holder_id(meta)
    return f"waiting on ack from {hid}" if hid else None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("holder_display.py is a library module; import it, don't run it")
