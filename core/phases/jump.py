#!/usr/bin/env python3
"""`klc jump <phase> <ticket> [--yes]` — cross-cut to another phase.

Only valid from a `<X>:ack` state (ack required before jumping). The
policy is "don't block, warn":

  klc jump <phase> <ticket>            # dry run: prints the plan
  klc jump <phase> <ticket> --yes      # execute the plan

The plan describes:
  - the target state (always `<phase>:work`)
  - inputs that are missing (the new phase may not have what it needs)
  - downstream phases whose artefacts will be moved to _superseded/
  - that budget counters will be reset

For recovery: any time the user finds themselves in a :work state they
no longer want, `klc abort` returns to the previous :ack; from there
they can `klc jump` freely.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
from artefacts import acquire_lock, write_prompt_card, LockedError  # noqa: E402


def _friendly_missing_ticket(ticket: str) -> int:
    sys.stderr.write(
        f"klc: unknown ticket {ticket!r}; run `klc intake {ticket}` "
        f"or `klc board` to list live tickets\n"
    )
    return 1


def _render_plan(plan: dict) -> str:
    lines = []
    lines.append(f"  from:            {plan['from']}")
    lines.append(f"  to:              {plan['to']}")
    if plan["missing_inputs"]:
        lines.append(f"  missing inputs:  {', '.join(plan['missing_inputs'])}")
    else:
        lines.append(f"  missing inputs:  (none — all inputs present)")
    if plan["supersede"]:
        lines.append(f"  supersede:       {', '.join(plan['supersede'])} "
                     f"→ _superseded/<ts>/")
    else:
        lines.append(f"  supersede:       (none — forward jump, no downstream yet)")
    lines.append(f"  reset budgets:   yes")
    return "\n".join(lines)


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc jump", description=__doc__)
    ap.add_argument("target_phase",
                    help="target phase id (e.g. build, design, review)")
    ap.add_argument("ticket")
    ap.add_argument("--yes", action="store_true",
                    help="execute the plan (default: dry run)")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        return _friendly_missing_ticket(args.ticket)

    # Forbid jumping to archived; that's a terminal state owned by learn.
    if args.target_phase == _ph.STATE_ARCHIVED:
        sys.stderr.write(
            "klc jump: target `archived` is not allowed. Archived is a "
            "terminal state reached through `klc ack --pick 1` on learn.\n"
        )
        return 2

    try:
        with acquire_lock(args.ticket):
            plan = _lc.jump(args.ticket, args.target_phase, dry_run=not args.yes)
            if not args.yes:
                print(f"jump plan for {args.ticket}:")
                print(_render_plan(plan))
                print()
                if plan["missing_inputs"]:
                    print("⚠  Some inputs are missing. The target phase's "
                          "agent will have to improvise or ask for them.")
                print(f"Run with --yes to execute: "
                      f"`klc jump {args.target_phase} {args.ticket} --yes`")
                return 0

            # Applied. Render the prompt card and return.
            meta = _lc.read_meta(args.ticket)
            card = write_prompt_card(args.ticket, args.target_phase, meta)
            print(f"→ {plan['to']}")
            print(f"  cat {card}")
            print(f"    # paste into your agent, then run `klc ack {args.ticket}`")
            return 0

    except LockedError as e:
        sys.stderr.write(f"klc jump: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"klc jump: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
