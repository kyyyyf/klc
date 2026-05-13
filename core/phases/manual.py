#!/usr/bin/env python3
"""Phase 6 — Manual check.

Generates (or delegates to LLM to generate) a checklist from AC +
edge cases in spec.md, waits for the human to tick it off, records
outcome in meta.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_dir, klc_ticket_meta_file  # noqa: E402
import lifecycle  # noqa: E402


def _read_meta(ticket: str) -> dict:
    return json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))


def _write_meta(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _prepare(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if meta["phase"] != "manual-pending":
        sys.stderr.write(
            f"klc manual: expected phase 'manual-pending', got {meta['phase']!r}\n"
        )
        return 1

    checklist = klc_ticket_dir(ticket) / "manual-checklist.md"
    if not checklist.exists():
        print(f"MANUAL_PENDING_LLM {ticket}")
        print(f"  prompt:  core/agents/manual-check.md")
        print(f"  input:   {klc_ticket_dir(ticket)}/spec.md")
        print(f"  output:  {checklist}")
        print()
        print(f"After the agent writes the checklist, walk through it then run:")
        print(f"  klc manual {ticket} --continue --outcome=<pass|fail>")
        return 0

    print(f"MANUAL_CHECKLIST_READY {ticket}")
    print(f"  checklist:  {checklist}")
    print(f"  continue:   klc manual {ticket} --continue --outcome=<pass|fail>")
    return 0


def _continue(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if args.outcome not in ("pass", "fail"):
        sys.stderr.write("klc manual --continue: --outcome=pass|fail required\n")
        return 2
    meta["manual_outcome"] = args.outcome
    meta.setdefault("metrics", {})["manual_outcome"] = args.outcome
    meta["metrics"]["manual_checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                          time.gmtime())
    _write_meta(ticket, meta)
    if args.outcome == "fail":
        sys.stderr.write(
            f"klc manual: outcome=fail. Use `klc back {ticket} --to build-pending "
            f"--reason ...` to rework.\n"
        )
        return 1
    lifecycle.advance(ticket, "manual-pending-ack", note="manual pass")
    print(f"MANUAL_OK {ticket}")
    print(f"  Ack with: klc ack {ticket} --for manual")
    return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc manual")
    ap.add_argument("ticket")
    ap.add_argument("--continue", dest="cont", action="store_true")
    ap.add_argument("--outcome", choices=["pass", "fail"], default=None)
    args = ap.parse_args(argv)
    return _continue(args) if args.cont else _prepare(args)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
