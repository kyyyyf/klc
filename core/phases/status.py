#!/usr/bin/env python3
"""`klc status <ticket>` — diagnostic summary.

Read-only: never advances the phase, never retries a failed step.
Emits a human-readable report of what's done, what's half-done, and
what the likely next command is.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    klc_ticket_dir,
    klc_ticket_meta_file,
)
import lifecycle  # noqa: E402


def _meta(ticket: str) -> dict | None:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc status")
    ap.add_argument("ticket")
    args = ap.parse_args(argv)

    meta = _meta(args.ticket)
    if meta is None:
        sys.stderr.write(f"klc status: unknown ticket {args.ticket!r}\n")
        return 1

    tdir = klc_ticket_dir(args.ticket)
    phase = meta.get("phase", "intake")
    track = meta.get("track") or "?"
    kind = meta.get("kind") or "?"

    print(f"TICKET {args.ticket}  phase={phase}  track={track}  kind={kind}")
    print(f"  dir:           {tdir}")

    # artefact presence
    for name in ("raw.md", "spec.md", "test-plan.md",
                 "design/options.md", "design/adr.md",
                 "impl-plan.md", "manual-checklist.md",
                 "retrospective.md"):
        p = tdir / name
        tag = "OK" if p.exists() else "--"
        print(f"  {tag} {name}")

    # budgets
    budgets = meta.get("budgets") or {}
    if budgets:
        print("  budgets:")
        for name, value in budgets.items():
            print(f"    {name}: {value}")

    # rework
    rework = meta.get("rework_count") or {}
    if rework:
        print("  rework_count:")
        for phase_name, n in rework.items():
            print(f"    {phase_name}: {n}")

    # next step suggestion
    allowed = sorted(lifecycle.TRANSITIONS.get(phase, set()))
    print(f"  allowed next:  {allowed or '(none; ticket terminal)'}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
