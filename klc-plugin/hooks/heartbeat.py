#!/usr/bin/env python3
"""heartbeat.py — CC plugin hook that keeps an actively-held ticket alive (KLC-064).

Called by hooks.json on UserPromptSubmit. Runs `klc heartbeat` for the current
identity, which (feature-ON only) refreshes `meta.holder.heartbeat_at` for every
ticket the identity holds in a `<phase>:work` state and CAS-pushes it — THROTTLED
to at most one push per window, so most prompt submits are a cheap read-only
no-op with no `klc-state` churn. Feature-OFF it is a pure no-op.

The hook is advisory only, so it ALWAYS exits 0 (non-blocking) and every error is
swallowed. Unlike remind, it produces NO user-facing output, so nothing is
forwarded to the prompt — it mirrors remind.py's KLC_BIN resolution but stays
silent.

Exit codes (CC hook contract):
  0 — always; heartbeat is silent, so nothing is written to stdout
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
            [*klc_cmd, "heartbeat"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return 0  # non-blocking: any error is silently swallowed
    # Heartbeat is silent by contract — never forward child output to the prompt.
    return 0


if __name__ == "__main__":
    sys.exit(main())
