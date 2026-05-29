#!/usr/bin/env python3
"""Bootstrap dependency checks — minimal requirements for klc init.

Checks only:
- Python 3.11+
- git
- jinja2

Exit 0 if all present, exit 1 with install instructions otherwise.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Import shared utilities
from . import log, warn, err, _check, _check_python_lib


def check_bootstrap() -> int:
    """Check bootstrap dependencies (Python 3.11+, git, jinja2).

    Returns:
        0 if all dependencies present
        1 if any dependency missing
    """
    log("Checking bootstrap dependencies")
    log(f"Python:            {sys.executable} ({sys.version})")

    missing: list[str] = []
    suggestions: list[str] = []

    # Check Python version (3.11+)
    version_info = sys.version_info
    if version_info < (3, 11):
        missing.append("python3.11+")
        # Handle both tuple and sys.version_info object
        major = version_info[0] if isinstance(version_info, tuple) else version_info.major
        minor = version_info[1] if isinstance(version_info, tuple) else version_info.minor
        suggestions.append(
            f"python3.11+: current version is {major}.{minor}, "
            f"but klc requires Python 3.11 or newer. "
            f"Install from https://www.python.org/downloads/"
        )
        warn(f"  Python version too old: {major}.{minor} < 3.11")
    else:
        major = version_info[0] if isinstance(version_info, tuple) else version_info.major
        minor = version_info[1] if isinstance(version_info, tuple) else version_info.minor
        log(f"  ok  Python {major}.{minor}")

    # Check git
    _check(missing, suggestions, name="git",
           hint="install git from https://git-scm.com")

    # Check jinja2
    _check_python_lib(missing, suggestions, module="jinja2",
                     install_hint=f"{sys.executable} -m pip install jinja2  OR  uv pip install jinja2")

    # Summary
    print("")
    if not missing:
        log("Bootstrap dependencies OK.")
        return 0

    err(f"Missing bootstrap dependencies: {' '.join(missing)}")
    err("Manual installation suggestions:")
    for s in suggestions:
        err(f"  - {s}")
    err("")
    err("After installing, re-run: python scripts/install_deps.py --bootstrap")
    return 1


if __name__ == "__main__":
    sys.exit(check_bootstrap())
