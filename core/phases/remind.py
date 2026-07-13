#!/usr/bin/env python3
"""`klc remind` — silent-by-default forgotten-ack advisory (KLC-059).

Emits exactly one line per ticket that the *current git identity* holds in a
`<phase>:work` state AND for which `phase_completion.can_complete(ticket, phase)`
returns True:

    KLC-xxx <phase> is done — run klc ack

It is silent when there is nothing to remind about, and it ALWAYS exits 0 —
it is advisory only and is wired into a non-blocking UserPromptSubmit hook, so
it must never crash the surrounding prompt.

Identity resolution is deliberately non-raising: unlike
`core/skills/identity.py::current()` (which raises SystemExit when nothing is
configured), `_git_user` falls back to `$USER` and finally the literal
"unknown", so `klc remind` degrades to silence rather than blowing up the hook.

`--statusline` is accepted and produces the same output (for status-line
integrations); it exists so callers can opt in explicitly without changing the
contract.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import phase_completion as _pc  # noqa: E402
import lifecycle as _lc  # noqa: E402
from _paths import klc_tickets_dir, project_root  # noqa: E402


def _git_user() -> str:
    """Resolve the acting identity without ever raising.

    Order: git user.email → git user.name → $USER → "unknown".
    Non-raising by design (see module docstring) so the hook stays silent
    rather than crashing when no identity is configured.
    """
    for key in ("user.email", "user.name"):
        try:
            r = subprocess.run(
                ["git", "config", "--get", key],
                capture_output=True, text=True, timeout=5,
            )
            out = r.stdout.strip()
            if out:
                return out
        except Exception:
            pass
    return os.environ.get("USER", "").strip() or "unknown"


def run(argv: list[str]) -> int:
    """Emit reminders for completable-held tickets. Always returns 0.

    The hook/statusline invokes this from an arbitrary cwd with PROJECT_ROOT
    set, so we chdir into the resolved project root for the duration of the
    scan (restored in `finally`). This ensures BOTH the git-identity read
    (`_git_user`) and the git-log-based completion checks (`can_complete`)
    target the project repo, not the caller's cwd — otherwise a held ticket
    recorded with the project's local identity would be silently missed.
    """
    # --statusline accepted; output is identical (AC-5), so it is a no-op.
    prev_cwd = os.getcwd()
    try:
        os.chdir(project_root())
    except Exception:
        # Cannot enter the project root → degrade to silence (advisory only).
        return 0
    try:
        return _scan()
    finally:
        try:
            os.chdir(prev_cwd)
        except Exception:
            pass


def _scan() -> int:
    """Scan tickets from the (already-chdir'd) project root. Returns 0."""
    identity = _git_user()

    tickets_dir = klc_tickets_dir()
    if not tickets_dir.exists():
        return 0

    for tdir in sorted(tickets_dir.iterdir()):
        if not tdir.is_dir():
            continue
        if not (tdir / "meta.json").exists():
            continue
        ticket = tdir.name
        try:
            meta = _lc.read_meta(ticket)
        except Exception:
            continue

        holder = meta.get("holder")
        if not isinstance(holder, dict):
            continue  # unheld or corrupt (non-dict) holder → skip robustly
        if holder.get("id") != identity:
            continue  # AC-3: held by someone else (or unheld) → skip

        phase_val = meta.get("phase", "")
        if not isinstance(phase_val, str):
            continue  # corrupt (non-string) phase → skip robustly
        if not phase_val.endswith(":work"):
            continue
        phase_id = phase_val.split(":", 1)[0]

        try:
            ok, _msg = _pc.can_complete(ticket, phase_id)
        except Exception:
            continue
        if ok:
            print(f"{ticket} {phase_id} is done — run klc ack")

    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
