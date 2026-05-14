#!/usr/bin/env python3
"""Phase 4 — Build.

Test-first loop: the test agent writes a failing test, impl-agent
makes it green, verifier runs the suite. The loop is LLM-driven and
must respect cycle limits (`core/skills/budget.py`).

This script is mostly a bookkeeper:
  - prepares the build bundle (spec + test-plan + impl-plan)
  - hands off to the build agents
  - `--continue` records a final diff, bumps phase to review-pending
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    klc_ticket_dir,
    klc_ticket_meta_file,
    project_root,
)
import lifecycle  # noqa: E402


def _read_meta(ticket: str) -> dict:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        import sys as _sys
        _sys.stderr.write(
            f"klc: unknown ticket {ticket!r}; run `klc intake {ticket}` "
            f"or `klc board` to list live tickets
"
        )
        raise SystemExit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def _write_meta(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _prepare(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if meta["phase"] != "build-pending":
        sys.stderr.write(
            f"klc build: expected phase 'build-pending', got {meta['phase']!r}\n"
        )
        return 1
    bundle = klc_ticket_dir(ticket) / "build-context"
    bundle.mkdir(parents=True, exist_ok=True)
    for name in ("spec.md", "test-plan.md", "impl-plan.md"):
        src = klc_ticket_dir(ticket) / name
        if src.exists():
            (bundle / name).write_text(src.read_text(encoding="utf-8"),
                                        encoding="utf-8")
    print(f"BUILD_PENDING_LLM {ticket}")
    print(f"  bundle:  {bundle}")
    print(f"  prompts: core/agents/test.md  (write failing test first)")
    print(f"           core/agents/impl.md  (make it pass)")
    print(f"  budget:  red_test_fix_attempts=3, mutation_fix_attempts=3")
    print()
    print(f"After tests are green, run: klc build {ticket} --continue")
    return 0


def _continue(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    # Snapshot current HEAD for review to diff against.
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"],
                           cwd=str(project_root()),
                           capture_output=True, text=True, timeout=5)
        head = r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        head = None
    meta.setdefault("metrics", {})["build_head_sha"] = head
    _write_meta(ticket, meta)
    lifecycle.advance(ticket, "review-pending", note="tests green")
    print(f"BUILD_OK {ticket}")
    print(f"  next: klc review {ticket}")
    return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc build")
    ap.add_argument("ticket")
    ap.add_argument("--continue", dest="cont", action="store_true")
    args = ap.parse_args(argv)
    return _continue(args) if args.cont else _prepare(args)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
