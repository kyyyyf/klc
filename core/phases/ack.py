#!/usr/bin/env python3
"""`klc ack` — human confirmation at a gate.

Four acks in the default flow:
    --for discovery   (discovery-pending-ack → test-plan-pending | build-pending)
    --for design      (design-pending-ack    → detailed-test-plan-pending)
    --for review      (review-pending-ack    → manual-pending  | integrate-pre)
    --for manual      (manual-pending-ack    → integrate-pre)

Also accepts --upgrade-track L to bump the track upward (never down)
at the discovery ack, per the guard invariant in process-phases.md §2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle  # noqa: E402


GATE_TO_NEXT = {
    # gate name → (expected current phase, default next phase)
    "discovery": ("discovery-pending-ack", None),  # next depends on track
    "design":    ("design-pending-ack",    "detailed-test-plan-pending"),
    "review":    ("review-pending-ack",    None),  # next depends on manual axis
    "manual":    ("manual-pending-ack",    "integrate-pre"),
}

TRACK_ORDER = {"XS": 0, "S": 1, "M": 2, "L": 3}


def _read_meta(ticket: str) -> dict:
    return json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))


def _write_meta(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _next_phase_for_discovery(meta: dict) -> str:
    track = meta.get("track") or "M"
    if track == "XS":
        return "build-pending"
    return "test-plan-pending"


def _next_phase_for_review(meta: dict) -> str:
    est = (meta.get("estimate") or {})
    if int(est.get("manual", 0) or 0) >= 2:
        return "manual-pending"
    return "integrate-pre"


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc ack")
    ap.add_argument("ticket")
    ap.add_argument("--for", dest="gate", required=True,
                    choices=list(GATE_TO_NEXT))
    ap.add_argument("--upgrade-track", default=None, choices=list(TRACK_ORDER),
                    help="bump track upward (only on --for discovery)")
    args = ap.parse_args(argv)

    meta = _read_meta(args.ticket)
    expected_phase, default_next = GATE_TO_NEXT[args.gate]
    if meta["phase"] != expected_phase:
        sys.stderr.write(
            f"klc ack: ticket is in {meta['phase']!r}, expected "
            f"{expected_phase!r} for gate {args.gate!r}\n"
        )
        return 1

    if args.upgrade_track:
        if args.gate != "discovery":
            sys.stderr.write("klc ack: --upgrade-track only valid for --for discovery\n")
            return 2
        cur = meta.get("track")
        if cur and TRACK_ORDER[args.upgrade_track] < TRACK_ORDER[cur]:
            sys.stderr.write(
                f"klc ack: cannot downgrade track {cur!r} → {args.upgrade_track!r}\n"
            )
            return 2
        meta["track"] = args.upgrade_track
        _write_meta(args.ticket, meta)

    if args.gate == "discovery":
        target = _next_phase_for_discovery(meta)
    elif args.gate == "review":
        target = _next_phase_for_review(meta)
    else:
        target = default_next

    lifecycle.advance(args.ticket, target, note=f"ack:{args.gate}")
    print(f"ACK_OK {args.ticket} gate={args.gate} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
