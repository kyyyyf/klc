#!/usr/bin/env python3
"""install_deps.py — check (and when possible auto-detect) framework deps.

Thin CLI dispatcher for modular dependency checks:
  --bootstrap  Check only Python 3.11+, git, jinja2 (minimal for klc init)
  --dev        Check only framework dev tools (mutation testing, etc.)
  (default)    Check project-runtime tools (LSP servers, language runtimes)

Exit 0 = every required dep present or auto-registered.
Exit 1 = at least one dep missing; manual instructions printed to stderr.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

# Add core/deps to sys.path
sys.path.insert(0, str(FRAMEWORK_ROOT / "core"))

# Also add core/skills for _paths and tools imports (used by project mode)
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="install-deps",
        description="Check framework dependencies (bootstrap, dev, or project modes)."
    )
    ap.add_argument("--bootstrap", action="store_true",
                    help="Check only bootstrap dependencies (Python 3.11+, git, jinja2)")
    ap.add_argument("--dev", action="store_true",
                    help="Check only framework dev tools (mutation testing, etc.)")
    ap.add_argument("--strict", action="store_true",
                    help="Treat optional tools as required (project mode only)")
    args = ap.parse_args(argv)

    # Initialize logging
    try:
        from _paths import klc_dir, klc_logs_dir  # noqa: F401
        from deps import log_init  # noqa: F401

        klc_dir().mkdir(parents=True, exist_ok=True)
        log_path = klc_logs_dir() / "install-deps.log"
        log_init(log_path)
    except ImportError:
        # If _paths not available (framework not installed yet), skip logging init
        pass

    # Dispatch to appropriate mode
    if args.bootstrap:
        from deps.bootstrap import check_bootstrap
        return check_bootstrap()
    elif args.dev:
        from deps.dev import check_dev
        return check_dev()
    else:
        # Default: project mode (backward compat)
        from deps.project import check_project
        return check_project(strict=args.strict, framework_root=FRAMEWORK_ROOT)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
