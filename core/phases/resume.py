#!/usr/bin/env python3
"""`klc resume <ticket>` — re-enter the interrupted phase.

Mirrors `status` but actually invokes the matching phase command.
Idempotent: if the phase had already completed, the phase script
prints the existing artefact path and exits 0.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402


PHASE_TO_CMD = {
    "intake":                "intake",
    "discovery-running":     "discover",
    "discovery-pending-ack": None,   # waiting for `klc ack`
    "test-plan-pending":     "test-plan",
    "design-pending":        "design",
    "design-pending-ack":    None,
    "detailed-test-plan-pending": ["test-plan", "--detailed"],
    "build-pending":         "build",
    "review-pending":        "review",
    "review-pending-ack":    None,
    "manual-pending":        "manual",
    "manual-pending-ack":    None,
    "integrate-pre":         ["integrate", "pre"],
    "integrate-post":        None,
    "observe":               "observe",
    "learn":                 "learn",
}


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc resume")
    ap.add_argument("ticket")
    args = ap.parse_args(argv)

    meta_path = klc_ticket_meta_file(args.ticket)
    if not meta_path.exists():
        sys.stderr.write(f"klc resume: unknown ticket {args.ticket!r}\n")
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    phase = meta.get("phase", "intake")

    cmd = PHASE_TO_CMD.get(phase)
    if cmd is None:
        print(f"klc resume: ticket is in {phase!r}; nothing to re-enter.")
        if phase.endswith("-ack"):
            gate = phase.split("-pending-ack")[0]
            print(f"  run: klc ack {args.ticket} --for {gate}")
        return 0

    klc = Path(__file__).resolve().parent.parent.parent / "scripts" / "klc"
    if isinstance(cmd, list):
        full = [str(klc), *cmd, args.ticket]
    else:
        full = [str(klc), cmd, args.ticket]
    print(f"resuming: {' '.join(full)}")
    return subprocess.call(full)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
