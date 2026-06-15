#!/usr/bin/env python3
"""`klc retrack <KEY> <track> --reason "..."` — sanctioned track change.

The route heuristic (KLC-013/KLC-018) is upward-biased and downgrade-forbidden
to prevent under-scoping. But a thorough write-up of a small task over-routes
the track (the `raw length` signal uses word count as a complexity proxy), and
there was no sanctioned way to correct it. retrack is the operator-only, audited
mechanism that changes the track in BOTH directions.

It records {from_track, to_track, reason, ts} in meta.phase_history (audit trail)
and stamps meta.track_source="operator" so nothing downstream treats the stale
route_hint as the authoritative track. It refuses if the new track's phase set
does not include the current phase (would corrupt the state machine).

Operator-only by design: this verb is never embedded in an agent prompt, so an
agent cannot silently game the track downward — preserving KLC-018's intent.
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

_VALID_TRACKS = ("XS", "S", "M", "L")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc retrack", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("track", choices=_VALID_TRACKS,
                    help="target track (XS/S/M/L); downgrade allowed")
    ap.add_argument("--reason", required=True,
                    help="why the track is being changed (recorded in the audit trail)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc retrack: unknown ticket {args.ticket!r}; run `klc intake` first\n"
        )
        return 1

    try:
        meta = _lc.read_meta(args.ticket)
    except FileNotFoundError as e:
        sys.stderr.write(f"klc retrack: {e}\n")
        return 1

    old_track = meta.get("track") or "M"
    new_track = args.track

    if new_track == old_track:
        sys.stderr.write(
            f"klc retrack: ticket {args.ticket} is already on track {new_track}; "
            f"nothing to do.\n"
        )
        return 1

    # Compatibility guard: the current phase must exist in the target track.
    phase_value = meta.get("phase") or ""
    if phase_value == _ph.STATE_ARCHIVED:
        sys.stderr.write(
            f"klc retrack: ticket {args.ticket} is archived; cannot retrack a "
            f"terminal ticket.\n"
        )
        return 1
    try:
        cur_pid, _ = _ph.parse_state(phase_value)
    except ValueError:
        sys.stderr.write(
            f"klc retrack: meta.json:phase is unparseable: {phase_value!r}\n"
        )
        return 1

    target_phase_ids = {p.id for p in _ph.load_phases().track_phases(new_track)}
    if cur_pid not in target_phase_ids:
        sys.stderr.write(
            f"klc retrack: cannot move {args.ticket} to track {new_track} — its "
            f"phase set does not include the current phase {cur_pid!r}. "
            f"Advance or jump to a phase common to both tracks first.\n"
        )
        return 1

    # Apply: change track, stamp source, append audit entry.
    meta["track"] = new_track
    meta["track_source"] = "operator"
    history = meta.setdefault("phase_history", [])
    history.append({
        "event":      "retrack",
        "phase":      phase_value,
        "from_track": old_track,
        "to_track":   new_track,
        "reason":     args.reason,
        "ts":         _now_iso(),
    })
    _lc.write_meta(args.ticket, meta)

    if args.json:
        print(json.dumps({
            "ticket":     args.ticket,
            "track":      new_track,
            "from_track": old_track,
            "phase":      phase_value,
            "reason":     args.reason,
        }))
    else:
        print(f"→ {args.ticket} retracked {old_track} → {new_track}")
        print(f"  reason: {args.reason}")
        print(f"  (track_source=operator; recorded in phase_history)")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
