#!/usr/bin/env python3
"""remind.py — CC plugin hook that emits a forgotten-ack reminder.

Called by hooks.json on UserPromptSubmit. Runs `klc remind` for the current
identity; any reminder text `klc remind` prints goes to stdout for CC to
display. The hook is advisory only, so it ALWAYS exits 0 (non-blocking) —
every error is swallowed. It mirrors the structure of gate.py's KLC_BIN
resolution but never blocks the prompt.

Exit codes (CC hook contract):
  0 — always; reminder text (if any) goes to stdout for CC to display
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys


def main() -> int:
    klc_bin = os.environ.get("KLC_BIN", "klc")
    # KLC_BIN may be "python3 /path/to/klc" — split it into a list.
    klc_cmd = shlex.split(klc_bin) if " " in klc_bin else [klc_bin]
    try:
        subprocess.run(
            [*klc_cmd, "remind"],
            capture_output=False, timeout=10,
        )
    except Exception:
        return 0  # non-blocking: any error is silently swallowed
    return 0


if __name__ == "__main__":
    sys.exit(main())
