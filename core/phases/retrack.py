#!/usr/bin/env python3
"""`klc retrack <KEY> <track> --reason "..."` — deprecated alias of `klc fix <KEY> track`.

KLC-178 moved the sanctioned track change into `klc fix`. This module keeps
`check_track_change`, the one refusal engine both verbs share, and a thin `run`
that translates its argv and delegates to `fix.run`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402

_VALID_TRACKS = ("XS", "S", "M", "L")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_track_change(ticket: str, meta: dict, new_track: str) -> str | None:
    """Why `ticket` cannot move to `new_track`, or None when the move is allowed.

    The one refusal engine shared by `klc retrack` and `klc fix <KEY> track`
    (KLC-178): same track, terminal ticket, or an unparseable phase. A phase the target
    lane lacks is no longer a refusal (KLC-179): `lifecycle.switch_track` moves the
    ticket to the first missing fact of the new lane."""
    old_track = meta.get("track") or "M"
    if new_track == old_track:
        return f"ticket {ticket} is already on track {new_track}; nothing to do."
    phase_value = meta.get("phase") or ""
    if _ph.is_terminal(phase_value):
        return f"ticket {ticket} is {phase_value}; cannot retrack a terminal ticket."
    try:
        cur_pid, _ = _ph.parse_state(phase_value)
    except ValueError:
        return f"meta.json:phase is unparseable: {phase_value!r}"
    return None


def run(argv: list[str]) -> int:
    """Hidden alias of `klc fix <KEY> track <TRACK> --reason ...` (KLC-178).

    The dispatcher prints the one deprecation line; this only translates argv and
    delegates, so the refusals, lock envelope and meta.fixes[] record are fix's."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fix as _fix  # lazy: fix imports check_track_change from this module
    ap = argparse.ArgumentParser(prog="klc retrack", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("track", choices=_VALID_TRACKS,
                    help="target track (XS/S/M/L); downgrade allowed")
    ap.add_argument("--reason", required=True,
                    help="why the track is being changed (recorded in the audit trail)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)
    out = [args.ticket, "track", args.track, "--reason", args.reason]
    if args.json:
        out.append("--json")
    return _fix.run(out)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
