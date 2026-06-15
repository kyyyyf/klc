#!/usr/bin/env python3
"""gate.py — CC plugin hook that blocks advancing past a pick_required gate.

Called by hooks.json on UserPromptSubmit. Reads KLC_TICKET from env,
checks the current phase via `klc status --json`, and exits 1 if the
ticket is in pick_required:ack-needed (blocking the user prompt until
they pick explicitly with `klc ack --pick N`).

Exit codes (CC hook contract):
  0 — allow the prompt through
  1 — block; message on stderr is shown to the user
  2 — hook error; CC falls through (permissive)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def _klc_status_json(ticket: str) -> dict | None:
    """Run `klc status <ticket> --json` and return parsed JSON or None on error."""
    import shlex
    klc_bin = os.environ.get("KLC_BIN", "klc")
    # KLC_BIN may be "python3 /path/to/klc" — split it into a list.
    klc_cmd = shlex.split(klc_bin) if " " in klc_bin else [klc_bin]
    try:
        result = subprocess.run(
            [*klc_cmd, "status", ticket, "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def _phases_requiring_pick() -> set[str]:
    """Return phase ids that are pick_required.

    Loaded lazily so the hook has no import-time dependency on the
    framework being on PYTHONPATH.
    """
    fw_root = os.environ.get("KLC_FW_ROOT")
    if not fw_root:
        # Derive from this file's location: hooks/ → klc-plugin/ → fw_root
        fw_root = str(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))))

    try:
        sys.path.insert(0, os.path.join(fw_root, "core", "skills"))
        import phases as _ph
        ph = _ph.load_phases()
        return {p.id for p in ph.ordered if p.pick_required}
    except Exception:
        return set()


def main() -> int:
    ticket = os.environ.get("KLC_TICKET", "").strip()
    if not ticket:
        return 0  # no ticket in context — allow

    status = _klc_status_json(ticket)
    if status is None:
        return 0  # can't determine state — allow (permissive)

    phase_id = status.get("phase_id", "")
    state = status.get("state", "")

    if state != "ack-needed":
        return 0  # not in ack-needed — allow

    pick_required_phases = _phases_requiring_pick()
    if phase_id not in pick_required_phases:
        return 0  # ack-needed but no pick required — allow

    # Block: ticket is in pick_required:ack-needed and no pick made yet.
    sys.stderr.write(
        f"[klc gate] Ticket {ticket} is in {phase_id}:ack-needed "
        f"(pick required).\n"
        f"Run: klc ack {ticket} --pick N\n"
        f"(use `klc status {ticket}` to see pick options)\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
