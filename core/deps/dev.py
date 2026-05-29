#!/usr/bin/env python3
"""Dev dependency checks — framework contributor tools.

Checks only mutation testing tools and framework dev dependencies:
- mutmut (Python mutation testing)
- stryker (JS/TS mutation testing)
- cargo-mutants (Rust mutation testing)
- mull-runner (C++ mutation testing, advisory)

Does NOT check project-runtime tools (pylsp, clangd, etc.).

Exit 0 if all present, exit 1 with install instructions otherwise.
"""
from __future__ import annotations

import sys

# Import shared utilities
from . import log, warn, err, _check, _has


def check_dev() -> int:
    """Check framework dev dependencies (mutation testing tools).

    Returns:
        0 if all dependencies present
        1 if any dependency missing
    """
    log("Checking framework dev dependencies")

    missing: list[str] = []
    suggestions: list[str] = []

    # Mutation testing tools
    log("Checking mutation testing tools")
    _check(missing, suggestions, name="mutmut",
           hint="pip install mutmut  OR  pipx install mutmut")
    _check(missing, suggestions, name="stryker",
           hint="npm install -g @stryker-mutator/core")
    _check(missing, suggestions, name="cargo-mutants",
           hint="cargo install cargo-mutants")

    # mull-runner is advisory (C++ mutation testing; requires LLVM)
    if not _has("mull-runner"):
        warn("  missing  mull-runner (C++ mutation testing; advisory)")
        warn("    install: https://github.com/mull-project/mull")
        warn("    (requires LLVM; skip on Windows/UE projects)")
    else:
        log(f"  ok  mull-runner ({_has('mull-runner')})")

    # Summary
    print("")
    if not missing:
        log("Framework dev dependencies OK.")
        return 0

    err(f"Missing dev dependencies: {' '.join(missing)}")
    err("Manual installation suggestions:")
    for s in suggestions:
        err(f"  - {s}")
    err("")
    err("After installing, re-run: python scripts/install_deps.py --dev")
    return 1


if __name__ == "__main__":
    sys.exit(check_dev())
