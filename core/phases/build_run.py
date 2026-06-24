#!/usr/bin/env python3
"""`klc build-run <ticket>` — dispatch each impl-plan step to a fresh subagent.

Reads build/progress.md (creates it from impl-plan.md on first run).
For each pending step: generates the dependency-resolved brief, dispatches
a fresh claude subprocess, marks the step green or blocked.
Returns 0 when all steps are green, non-zero on the first blocked step.
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
    return build_orchestrator.run_build(args.ticket)
