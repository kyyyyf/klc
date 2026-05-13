#!/usr/bin/env python3
"""Phase 5 — Review.

Thin wrapper over the existing `review.sh`. Infers --diff and --spec
from the ticket's meta.json and runs the multi-agent review, then
bumps phase to review-pending-ack on APPROVED (or leaves pending on
CHANGES REQUESTED).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    framework_root,
    klc_ticket_dir,
    klc_ticket_meta_file,
    project_root,
)
import lifecycle  # noqa: E402


def _read_meta(ticket: str) -> dict:
    return json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc review")
    ap.add_argument("ticket")
    ap.add_argument("--continue", dest="cont", action="store_true")
    ap.add_argument("--diff", default=None,
                    help="override the diff ref/file (defaults to HEAD)")
    ap.add_argument("--external", action="store_true")
    args = ap.parse_args(argv)

    meta = _read_meta(args.ticket)

    if args.cont:
        # User confirms review APPROVED (manual step after reading the report)
        if meta["phase"] != "review-pending":
            sys.stderr.write(
                f"klc review --continue: expected phase 'review-pending', "
                f"got {meta['phase']!r}\n"
            )
            return 1
        lifecycle.advance(args.ticket, "review-pending-ack",
                          note="user confirmed APPROVED")
        print(f"REVIEW_READY {args.ticket}")
        print(f"  Ack with: klc ack {args.ticket} --for review")
        return 0

    if meta["phase"] != "review-pending":
        sys.stderr.write(
            f"klc review: expected phase 'review-pending', got {meta['phase']!r}\n"
        )
        return 1

    spec = klc_ticket_dir(args.ticket) / "spec.md"
    cmd = [
        str(framework_root() / "scripts" / "review.sh"),
        "--diff", args.diff or "HEAD",
        "--spec", str(spec),
    ]
    if args.external:
        cmd.append("--external")

    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(project_root())
    r = subprocess.run(cmd, env=env)
    if r.returncode == 0:
        print(f"REVIEW_APPROVED {args.ticket}")
        print(f"  confirm with: klc review {args.ticket} --continue")
    else:
        print(f"REVIEW_CHANGES_REQUESTED {args.ticket}")
        print(f"  address blocking issues, then re-run klc review")
    return r.returncode


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
