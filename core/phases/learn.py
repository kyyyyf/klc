#!/usr/bin/env python3
"""Phase 9 — Learn.

Invokes the retrospective agent, collects final metrics, runs the
rollup, optionally runs `serena_deny.py propose`, then archives the
ticket into `.klc/tickets/archive/<KEY>/`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    klc_ticket_dir,
    klc_ticket_meta_file,
    klc_tickets_archive_dir,
)
import lifecycle  # noqa: E402


def _meta(ticket: str) -> dict:
    return json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))


def _write(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _prepare(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _meta(ticket)
    if meta["phase"] != "learn":
        sys.stderr.write(
            f"klc learn: expected phase 'learn', got {meta['phase']!r}\n"
        )
        return 1

    retro = klc_ticket_dir(ticket) / "retrospective.md"
    if not retro.exists():
        print(f"LEARN_PENDING_LLM {ticket}")
        print(f"  prompt:  core/agents/retrospective.md")
        print(f"  input:   all artefacts under {klc_ticket_dir(ticket)}")
        print(f"           meta.json (phase history, metrics, rework)")
        print(f"  output:  {retro}")
        print()
        print(f"After the agent writes retrospective.md:")
        print(f"  klc learn {ticket} --continue")
        return 0

    print(f"LEARN_RETRO_READY {ticket}")
    print(f"  continue: klc learn {ticket} --continue")
    return 0


def _continue(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _meta(ticket)
    retro = klc_ticket_dir(ticket) / "retrospective.md"
    if not retro.exists():
        sys.stderr.write("klc learn --continue: retrospective.md missing\n")
        return 1

    # Metrics rollup
    metrics_script = SKILLS / "metrics.py"
    subprocess.run([sys.executable, str(metrics_script), "rollup"], check=False)

    # Optional serena-deny harvest
    sd = SKILLS / "serena_deny.py"
    if sd.exists() and not args.skip_deny:
        subprocess.run([sys.executable, str(sd), "propose",
                        "--min-tickets", "2"], check=False)

    # Advance to archived, then move the directory.
    lifecycle.advance(ticket, "archived", note="learn done")

    archive_root = klc_tickets_archive_dir()
    archive_root.mkdir(parents=True, exist_ok=True)
    dst = archive_root / ticket
    src = klc_ticket_dir(ticket)
    if dst.exists():
        sys.stderr.write(
            f"klc learn: archive target {dst} already exists; "
            "rename it manually and re-run.\n"
        )
        return 1
    shutil.move(str(src), str(dst))
    print(f"LEARN_OK {ticket}")
    print(f"  archived: {dst}")
    return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc learn")
    ap.add_argument("ticket")
    ap.add_argument("--continue", dest="cont", action="store_true")
    ap.add_argument("--skip-deny", action="store_true",
                    help="skip serena_deny.py propose during learn")
    args = ap.parse_args(argv)
    return _continue(args) if args.cont else _prepare(args)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
