#!/usr/bin/env python3
"""`klc build-run <ticket>` — dispatch each impl-plan step to a fresh subagent.

Progress is derived from git and build/steps.json (`step_state`); no ledger file.
For each step that is not green: generates the dependency-resolved brief,
dispatches a fresh claude subprocess, then records the step's VERIFY.
Returns 0 when all steps are green, non-zero on the first step that is not.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))

import build_orchestrator  # noqa: E402


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc build-run", description=__doc__)
    ap.add_argument("ticket")
    args = ap.parse_args(argv)
    try:
        return build_orchestrator.run_build(args.ticket)
    except ValueError as exc:
        sys.stderr.write(f"klc build-run: {exc}\n")
        return 1
