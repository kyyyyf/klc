#!/usr/bin/env python3
"""`klc work <ticket>` — print the single next required action, read-only.

Answers "what is the next thing to do on this ticket?" in one deterministic
report, derived entirely from `phases.yml` plus the ticket's `meta.json`:

  - at `<phase>:work`   — the prompt-card path to paste, the phase's expected
                          output artifacts, and a verify command.
  - at `<phase>:ack-needed` — the available `klc ack --pick` picks.
  - at `<phase>:ack`    — the `klc next` hint to advance.
  - archived            — a clean "nothing to do" report.

This verb is strictly READ-ONLY. It reads meta via `lifecycle.read_meta_ro`
(NOT `current_state`, which would persist a legacy-phase migration and dirty the
tree — KLC-047 AC-4). It never writes meta.json.

The build prompt card is the per-step card written by `klc step`
(`build/_prompt_step_<N>.md`), not a flat `build/_prompt.md`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402


def next_action(ticket: str) -> dict:
    """Resolve the current state and the next-action descriptor for `ticket`.

    Pure read: uses `read_meta_ro` so a legacy-phase ticket is never rewritten.
    The caller must have verified the ticket exists (see `run`).
    """
    meta = _lc.read_meta_ro(ticket)
    phase_value = meta.get("phase") or "intake:ack-needed"

    # Archived is a terminal pseudo-state no phase owns — handle it FIRST,
    # exactly as status.py does, before parse_state.
    if phase_value == _ph.STATE_ARCHIVED:
        return {"ticket": ticket, "phase": "archived", "state": "archived",
                "next": "(ticket archived — nothing to do)"}

    pid, state = _ph.parse_state(phase_value)
    ph = _ph.load_phases().by_id(pid)
    verify = ("python3 -m pytest tests/ -q --ignore=tests/fixtures"
              if pid == "build" else f"klc status {ticket}")
    out: dict = {"ticket": ticket, "phase": pid, "state": state,
                 "outputs": list(ph.outputs), "verify": verify}

    if state == _ph.STATE_WORK:
        if pid == "build":
            # Build is a multi-step loop; point at the current step's card
            # (written by `klc step`), not a flat _prompt.md.
            step = meta.get("impl_step") or 1
            out["prompt"] = f".klc/tickets/{ticket}/build/_prompt_step_{step}.md"
        else:
            out["prompt"] = f".klc/tickets/{ticket}/{pid}/_prompt.md"
    elif state == _ph.STATE_ACK_NEEDED:
        out["picks"] = [(p.id, p.label) for p in ph.picks]
    else:  # ack
        out["next"] = f"klc next {ticket}"
    return out


def _render(info: dict) -> str:
    ticket = info["ticket"]
    if info["phase"] == "archived":
        return f"{ticket}: archived — nothing to do."

    lines = [f"{ticket}  {info['phase']}:{info['state']}", ""]
    state = info["state"]
    if state == _ph.STATE_WORK:
        lines.append(f"  prompt:  cat {info['prompt']}")
        if info.get("outputs"):
            lines.append(f"  outputs: {', '.join(info['outputs'])}")
        lines.append(f"  verify:  {info['verify']}")
        lines.append(f"  done:    klc ack {ticket}  (with --pick if required)")
    elif state == _ph.STATE_ACK_NEEDED:
        if info.get("picks"):
            lines.append(f"  → run `klc ack {ticket} --pick N`:")
            for pid, label in info["picks"]:
                lines.append(f"      {pid} = {label}")
        else:
            lines.append(f"  → run `klc ack {ticket}`")
    else:  # ack
        lines.append(f"  → run `{info['next']}` to advance")
    return "\n".join(lines)


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc work", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)

    # Read-only guard: check existence BEFORE any meta read/write, mirroring
    # step.py / status.py, so a missing ticket never creates or touches meta.
    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc work: unknown ticket {args.ticket!r}; "
            f"run `klc intake {args.ticket}` or `klc board`\n"
        )
        return 1

    try:
        info = next_action(args.ticket)  # read-only; never writes meta
    except (ValueError, KeyError):
        # A corrupt/unparseable phase string or an unknown phase id must not
        # crash with a raw traceback — mirror status.py's clean error path.
        sys.stderr.write(
            f"klc work: meta.json:phase is unparseable for {args.ticket!r}; "
            f"run `klc status {args.ticket}`\n"
        )
        return 1
    print(json.dumps(info) if args.json else _render(info))
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
