#!/usr/bin/env python3
"""`klc run <ticket> [--cap N] [--json]` — the autonomous runner (KLC-046).

Drive a ticket through the state machine on its own: at each `:work` state it
dispatches the phase agent (build via the KLC-042 orchestrator, others via
`runner.run_agent`) then applies the KLC-045 gate-policy through the SAME
`klc ack --auto` path a human would take. It advances clean conditional gates
and PAUSES — never proceeds — on a decision gate, a dirty conditional gate, or a
guardrail (integrate/merge, a budget ceiling, or the consecutive-auto cap).

SINGLE-USER / feature-off only: if the multi-user state feature is ON, the
runner refuses. Exit code: 0 when the ticket reaches a terminal/clean stop
(archived), 2 when the loop paused (a human must act), 1 on a refusal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import autorunner  # noqa: E402


def _render(res: "autorunner.RunResult") -> str:
    lines = [f"transitions: {' → '.join(res.transitions) if res.transitions else '(none)'}"]
    if res.paused_at is None and res.reason is None:
        lines.append("result: DONE (archived)")
    elif res.paused_at is None:
        lines.append(f"result: {res.reason}")
    else:
        lines.append(f"result: PAUSED at {res.paused_at}")
        lines.append(f"reason: {res.reason}")
    return "\n".join(lines)


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc run", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("--cap", type=int, default=None,
                    help="max consecutive auto-transitions before pausing (runaway backstop)")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = ap.parse_args(argv)

    res = autorunner.run(args.ticket, cap=args.cap)

    if args.json:
        print(json.dumps({"ticket": args.ticket, "transitions": res.transitions,
                          "paused_at": res.paused_at, "reason": res.reason}))
    else:
        print(_render(res))

    # Refusal (feature-on): reason set but no paused_at and no transitions taken.
    if res.paused_at is None and res.reason is not None:
        return 1
    return 0 if res.paused_at is None else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
