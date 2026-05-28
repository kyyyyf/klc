#!/usr/bin/env python3
"""scratch.py — operate on a ticket's scratchpad.

Scratchpad is per-ticket externalized agent memory (see `framework-changes.md`
section 3). Files live in `.klc/tickets/<ticket>/scratch/*.md`, carry the
same inline-item tags as final artefacts, and survive context compression
between sessions.

Subcommands:

    new       — create a new session file from the template
    list      — list sessions in chronological order (oldest first)
    read      — concatenate every session with a SESSION header, so a
                resuming agent can feed the whole scratch to its LLM
                in one read (read-back protocol)
    archive   — move scratch/ aside (no delete) when the ticket is
                integrated; used by the integrate-agent

Limits enforced on `new`:
    - at most MAX_SCRATCH_FILES per ticket (consolidate if over)
    - no individual file larger than MAX_SCRATCH_BYTES (split by session)

Defaults match `framework-changes.md` section 3.5: 10 files, 50 KB each.

Usage:
    scratch.py new    --ticket TICK-123 --agent impl-agent
                      --phase build --purpose "trace connection starvation"
    scratch.py list   --ticket TICK-123
    scratch.py read   --ticket TICK-123
    scratch.py archive --ticket TICK-123
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.shared.paths import (  # noqa: E402
    framework_root,
    klc_ticket_dir,
    klc_ticket_scratch_dir,
    klc_tickets_archive_dir,
)

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:  # pragma: no cover — jinja2 is a declared dependency
    sys.stderr.write("scratch: jinja2 required (pip install jinja2)\n")
    sys.exit(2)


MAX_SCRATCH_FILES = 10
MAX_SCRATCH_BYTES = 50 * 1024


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(framework_root() / "core" / "templates")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _list_sessions(scratch_dir: Path) -> list[Path]:
    if not scratch_dir.exists():
        return []
    # Sort by filename. The "NNN-<slug>.md" convention keeps chronology
    # even if mtime is unreliable (touch/rsync).
    return sorted(scratch_dir.glob("*.md"))


def _next_session_number(scratch_dir: Path) -> int:
    existing = _list_sessions(scratch_dir)
    if not existing:
        return 1
    nums = []
    for f in existing:
        head = f.stem.split("-", 1)[0]
        if head.isdigit():
            nums.append(int(head))
    return (max(nums) + 1) if nums else len(existing) + 1


def _slugify(text: str, max_len: int = 40) -> str:
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")
    return (slug or "session")[:max_len]


def cmd_new(args: argparse.Namespace) -> int:
    scratch_dir = klc_ticket_scratch_dir(args.ticket)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    existing = _list_sessions(scratch_dir)
    if len(existing) >= MAX_SCRATCH_FILES:
        sys.stderr.write(
            f"scratch: {len(existing)} session files already, limit is "
            f"{MAX_SCRATCH_FILES}. Consolidate findings into the ticket's "
            f"artefacts before opening a new session.\n"
        )
        return 1

    for f in existing:
        if f.stat().st_size > MAX_SCRATCH_BYTES:
            sys.stderr.write(
                f"scratch: {f} exceeds {MAX_SCRATCH_BYTES} bytes. Split "
                f"it or move resolved findings into an artefact.\n"
            )
            return 1

    n = _next_session_number(scratch_dir)
    slug = _slugify(args.purpose)
    filename = f"{n:03d}-{slug}.md"
    target = scratch_dir / filename

    env = _jinja_env()
    tpl = env.get_template("scratch-session.md.j2")
    target.write_text(
        tpl.render(
            created=_now_iso(),
            agent=args.agent,
            ticket=args.ticket,
            phase=args.phase,
            purpose=args.purpose,
            session=n,
        ),
        encoding="utf-8",
    )
    print(f"SCRATCH_NEW {target}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    scratch_dir = klc_ticket_scratch_dir(args.ticket)
    for f in _list_sessions(scratch_dir):
        size = f.stat().st_size
        print(f"{f}\t{size}B")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    scratch_dir = klc_ticket_scratch_dir(args.ticket)
    sessions = _list_sessions(scratch_dir)
    if not sessions:
        sys.stderr.write(f"scratch: no sessions in {scratch_dir}\n")
        return 1
    # One concatenated stream with clear delimiters so the agent can
    # parse sessions back apart if it wants. The read-back protocol asks
    # the agent to consume this verbatim.
    for f in sessions:
        sys.stdout.write(f"\n<!-- BEGIN SESSION {f.name} -->\n")
        sys.stdout.write(f.read_text(encoding="utf-8"))
        sys.stdout.write(f"\n<!-- END SESSION {f.name} -->\n")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    """Move scratch/ into <ticket>/archived-scratch-<timestamp>/ so
    the trail survives integration. Scratchpads are not deleted."""
    scratch_dir = klc_ticket_scratch_dir(args.ticket)
    if not scratch_dir.exists():
        # Nothing to do — consistent with noop-on-empty everywhere else.
        print(f"SCRATCH_ARCHIVE_NOOP {args.ticket}")
        return 0
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst = klc_ticket_dir(args.ticket) / f"archived-scratch-{stamp}"
    shutil.move(str(scratch_dir), str(dst))
    print(f"SCRATCH_ARCHIVED {dst}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="create a new scratch session")
    p_new.add_argument("--ticket", required=True)
    p_new.add_argument("--agent", required=True,
                       help="short agent name, e.g. impl-agent")
    p_new.add_argument("--phase", required=True,
                       help="discovery | design | build | review | learn")
    p_new.add_argument("--purpose", required=True,
                       help="one-line reason for the session, becomes slug")
    p_new.set_defaults(func=cmd_new)

    p_list = sub.add_parser("list", help="list sessions in chronological order")
    p_list.add_argument("--ticket", required=True)
    p_list.set_defaults(func=cmd_list)

    p_read = sub.add_parser("read", help="concatenate all sessions for read-back")
    p_read.add_argument("--ticket", required=True)
    p_read.set_defaults(func=cmd_read)

    p_arc = sub.add_parser("archive", help="move scratch aside after integrate")
    p_arc.add_argument("--ticket", required=True)
    p_arc.set_defaults(func=cmd_archive)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
