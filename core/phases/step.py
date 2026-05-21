#!/usr/bin/env python3
"""`klc step <ticket> <N>` — generate a minimal prompt card for build step N.

Does NOT change the ticket phase. Renders
`.klc/tickets/<ticket>/build/_prompt_step_N.md` using the impl-step
template: Goals + ACs from spec, current step only from impl-plan,
LSP navigation instructions.

Use during the Build TDD loop instead of the full _prompt.md to keep
each iteration's context minimal.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
from artefacts import write_step_card  # noqa: E402


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc step", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("step", type=int, help="step number (1-based)")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc: unknown ticket {args.ticket!r}; run `klc intake {args.ticket}` "
            f"or `klc board` to list live tickets\n"
        )
        return 1

    meta = _lc.read_meta(args.ticket)
    card = write_step_card(args.ticket, args.step, meta)
    print(f"→ step-{args.step} card written")
    print(f"  cat {card}")
    print(f"    # paste into your agent")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
