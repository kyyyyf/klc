#!/usr/bin/env python3
"""Current-user identity resolution for KLC.

`current()` resolves the acting user's identity from git config, falling back
to the shell `$USER`, and exits with a setup instruction if nothing is
configured. This is the single source of truth for "who owns this ticket".
"""
from __future__ import annotations

import os
import subprocess


def current() -> str:
    """Return the current user's identity.

    Resolution order:
      1. `git config --get user.email`
      2. `git config --get user.name`
      3. the `$USER` environment variable

    Whitespace-only values are treated as unset. If git is unavailable
    (not on PATH → OSError) or slow (TimeoutExpired), that source is skipped.
    Raises SystemExit with a setup instruction when nothing is configured.
    """
    for key in ("user.email", "user.name"):
        try:
            r = subprocess.run(["git", "config", "--get", key],
                               capture_output=True, text=True, timeout=5)
            out = r.stdout.strip()
            if out:
                return out
        except (OSError, subprocess.TimeoutExpired):
            pass
    user_env = os.environ.get("USER", "").strip()
    if user_env:
        return user_env
    raise SystemExit(
        "KLC: git identity not configured.  Run:\n"
        "  git config --global user.email you@example.com\n"
        "  git config --global user.name  'Your Name'"
    )
