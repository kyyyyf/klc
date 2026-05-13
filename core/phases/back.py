#!/usr/bin/env python3
"""`klc back <ticket> --to <phase> --reason "..."` — rework jump.

The only sanctioned way to move a ticket backwards. Wraps
`lifecycle.back`, which writes an audit entry to `phase_history`,
increments rework_count for the source phase, and switches
meta.json:phase.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
import lifecycle  # noqa: E402


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc back")
    ap.add_argument("ticket")
    ap.add_argument("--to", dest="to", required=True,
                    help="target phase — must precede the current phase")
    ap.add_argument("--reason", required=True)
    args = ap.parse_args(argv)

    try:
        lifecycle.back(args.ticket, args.to, reason=args.reason)
    except ValueError as exc:
        sys.stderr.write(f"klc back: {exc}\n")
        return 1
    print(f"BACK_OK {args.ticket} -> {args.to}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
