#!/usr/bin/env python3
"""Phase 0 — Intake.

Creates `.klc/tickets/<KEY>/`, writes meta.json + raw.md, appends to
the global index. Does NOT call Serena, does NOT touch Jira, does NOT
create git branches. Leaves the ticket in `intake:ack-needed`.

Usage:
    klc intake <JIRA-KEY> [--kind feature|bug|tech] "<desc>"
    cat bug.txt | klc intake <JIRA-KEY> --stdin [--kind bug]

See process-phases.md §3 for the full contract.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))
from _paths import (  # noqa: E402
    klc_config_dir,
    klc_global_tickets_index,
    klc_ticket_dir,
    klc_ticket_meta_file,
    klc_ticket_raw_file,
)


DEFAULT_KEY_RE = r"^[A-Z][A-Z0-9]+-\d+$"


def _load_key_pattern() -> re.Pattern:
    r"""Read the regex from .klc/config/ticket-id.yml.

    YAML semantics we honour (by hand — PyYAML isn't a hard dep of this
    skill): single-quoted strings are literal; double-quoted strings
    obey backslash escapes (so `"\\d"` means `\d`, as it would through
    a real parser).
    """
    cfg = klc_config_dir() / "ticket-id.yml"
    if not cfg.exists():
        return re.compile(DEFAULT_KEY_RE)
    for line in cfg.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("pattern:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value.startswith("'") and value.endswith("'"):
            raw = value[1:-1]        # single-quoted → literal
        elif value.startswith('"') and value.endswith('"'):
            raw = bytes(value[1:-1], "utf-8").decode("unicode_escape")
        else:
            raw = value              # bare scalar, no escapes in YAML
        return re.compile(raw)
    return re.compile(DEFAULT_KEY_RE)


def _load_jira_url(ticket: str) -> str | None:
    cfg = klc_config_dir() / "jira.yml"
    if not cfg.exists():
        return None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("url_template:"):
            tmpl = line.split(":", 1)[1].strip().strip('"').strip("'")
            return tmpl.replace("{key}", ticket)
    return None


def _git_user() -> str:
    for key in ("user.email", "user.name"):
        try:
            r = subprocess.run(["git", "config", "--get", key],
                               capture_output=True, text=True, timeout=5)
            out = r.stdout.strip()
            if out:
                return out
        except (OSError, subprocess.TimeoutExpired):
            pass
    return os.environ.get("USER", "unknown")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc intake", description=__doc__)
    ap.add_argument("--kind", choices=["feature", "bug", "tech", "unknown"],
                    default=None)
    ap.add_argument("--stdin", action="store_true",
                    help="read description from stdin")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing intake data")
    ap.add_argument("ticket", help="Jira-style ticket key, e.g. CRUSH-4502")
    ap.add_argument("description", nargs="*",
                    help="description words (any position; quote if it contains options)")
    # parse_intermixed_args lets the positional description follow --kind
    # without argparse dropping the tail as "unrecognized".
    args = ap.parse_intermixed_args(argv)
    if isinstance(args.description, list):
        args.description = " ".join(args.description) if args.description else None

    pat = _load_key_pattern()
    if not pat.match(args.ticket):
        sys.stderr.write(
            f"klc intake: invalid key {args.ticket!r}; expected {pat.pattern}\n"
        )
        return 2

    if args.stdin:
        desc = sys.stdin.read().strip()
    else:
        desc = (args.description or "").strip()
    if not desc:
        sys.stderr.write("klc intake: description required "
                         "(positional or --stdin)\n")
        return 2

    tdir = klc_ticket_dir(args.ticket)
    existing = klc_ticket_meta_file(args.ticket).exists()
    if existing and not args.force:
        meta = json.loads(klc_ticket_meta_file(args.ticket).read_text(encoding="utf-8"))
        if not (meta.get("phase") or "").startswith("intake"):
            sys.stderr.write(
                f"klc intake: ticket {args.ticket} already in phase "
                f"{meta.get('phase')!r}. Use `klc status` or `klc abort`.\n"
            )
            return 1
        sys.stderr.write(
            f"klc intake: {args.ticket} already at intake; use --force to overwrite.\n"
        )
        return 1

    t0 = _dt.datetime.now(_dt.timezone.utc)
    tdir.mkdir(parents=True, exist_ok=True)

    jira_url = _load_jira_url(args.ticket)
    raw_header = [
        "---",
        f"ticket: {args.ticket}",
    ]
    if jira_url:
        raw_header.append(f"jira_url: {jira_url}")
    raw_header += [
        f"kind_hint: {args.kind or 'unknown'}",
        f"created: {_now()}",
        "---",
        "",
    ]
    klc_ticket_raw_file(args.ticket).write_text(
        "\n".join(raw_header) + desc + "\n", encoding="utf-8"
    )

    meta = {
        "ticket":        args.ticket,
        "kind":          args.kind or "unknown",
        "kind_source":   "user" if args.kind else "intake-agent-pending",
        "phase":         "intake:ack-needed",
        "phase_history": [{"phase": "intake:ack-needed", "started_at": _now()}],
        "track":         None,
        "estimate":      None,
        "layer":         None,
        "affected_modules": [],
        "created":       _now(),
        "owner":         _git_user(),
        "jira_url":      jira_url,
        "links":         [],
        "rework_count":  {},
        "metrics":       {"intake_ms": int((_dt.datetime.now(_dt.timezone.utc) - t0).total_seconds() * 1000)},
    }
    klc_ticket_meta_file(args.ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # append to global index (append-only)
    idx = klc_global_tickets_index()
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "key":        args.ticket,
            "kind":       meta["kind"],
            "phase":      "intake",
            "created":    meta["created"],
        }, ensure_ascii=False) + "\n")

    print(f"INTAKE_OK {args.ticket}")
    print(f"  dir:   {tdir}")
    print(f"  kind:  {meta['kind']}")
    print(f"  → intake:ack-needed")
    print(f"  next:  klc ack {args.ticket}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
