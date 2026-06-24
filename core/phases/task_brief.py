#!/usr/bin/env python3
"""`klc task-brief <KEY> <N>` — write a dependency-resolved step brief.

Writes `.klc/tickets/<KEY>/build/step-N-brief.md` containing:
  - spec Goals + ACs (global constraints)
  - the target step's full body
  - only the Interfaces + COMMIT surface of each Depends-on step

Scaffolds an empty `step-N-impl-report.md` if one does not already exist.
Does NOT change the ticket phase.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file, klc_ticket_dir  # noqa: E402
import task_brief as _tb  # noqa: E402


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc task-brief", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("step", type=int, help="step number (1-based)")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc: unknown ticket {args.ticket!r}; run `klc intake {args.ticket}` "
            f"or `klc board` to list live tickets\n"
        )
        return 1

    try:
        text = _tb.build_step_brief(args.ticket, args.step)
    except ValueError as e:
        sys.stderr.write(f"task-brief: {e}\n")
        return 2

    build_dir = klc_ticket_dir(args.ticket) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    brief_path = build_dir / f"step-{args.step}-brief.md"
    brief_path.write_text(text, encoding="utf-8")

    report_path = build_dir / f"step-{args.step}-impl-report.md"
    if not report_path.exists() or not report_path.read_text(encoding="utf-8").strip():
        report_path.write_text(_tb._render_report_skeleton(args.ticket, args.step), encoding="utf-8")

    print(f"→ step-{args.step} brief written")
    print(f"  cat {brief_path}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
