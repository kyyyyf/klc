#!/usr/bin/env python3
"""serena_deny.py — harvest and manage the Serena query denylist.

The denylist stops `serena-call.py` from wasting tokens on queries
that are known-noisy for the project: engine-wide symbols, vendored
headers, generated code, and the like. Entries live in
`.klc/knowledge/serena-deny.yml` (project-owned, survives retros);
the framework ships an empty seed at `framework/config/serena-deny.yml`.

This skill is the maintenance side of that file:

    propose — scan per-ticket `.klc/tickets/*/serena-calls.log`, surface
              queries that recurred across tickets and look like
              candidates for denial. Output is a YAML snippet the
              retrospective agent (or a human) reviews and trims.
    add     — append a validated entry to the project denylist. Rejects
              malformed regex so broken patterns never reach runtime.
    list    — print the effective denylist (project overrides
              framework seed) — useful for reviewing what is in force.
    show-log — tail the call log for one ticket, filtered to
              relevant events.

This skill NEVER auto-adds entries. `propose` only prints a suggestion;
the human (or retrospective prompt) must copy-paste through `add`. That
asymmetry is deliberate — a denylist that silently grows on every run
turns into a graveyard of one-off mispredictions.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import (  # noqa: E402
    framework_root,
    klc_knowledge_dir,
    klc_serena_deny_file,
    klc_tickets_dir,
)


# --- YAML helpers (minimal; same approach as serena-call.py) ------------------

def _parse_deny_entries(text: str) -> list[dict]:
    """Tiny parser for `entries: [-{...}, ...]` shape. Tolerates
    comments and blank lines. Not a general YAML parser."""
    entries: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- "):
            if current:
                entries.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                current[k.strip()] = v.strip().strip('"').strip("'")
        elif ":" in stripped and current is not None:
            k, _, v = stripped.partition(":")
            current[k.strip()] = v.strip().strip('"').strip("'")
    if current:
        entries.append(current)
    return [e for e in entries if e.get("pattern")]


def _read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return _parse_deny_entries(path.read_text(encoding="utf-8"))


def _yaml_escape(value: str) -> str:
    """Quote a value if it contains YAML-sensitive characters."""
    if re.search(r"[:#\n]|^[\s\-]|[\s\-]$", value) or value == "":
        return '"' + value.replace('"', '\\"') + '"'
    return value


# --- log reading --------------------------------------------------------------

def _iter_log_records(log_path: Path):
    if not log_path.exists():
        return
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


# --- propose ------------------------------------------------------------------

def cmd_propose(args: argparse.Namespace) -> int:
    """Find (op, subject) pairs that recurred across N+ tickets and
    suggest denylist patterns. 'Recurred' here means the same pair
    appeared in at least `--min-tickets` different per-ticket logs;
    one-off queries are never candidates.

    We emphasise cross-ticket reuse rather than raw frequency: a tight
    debug loop may legitimately hit the same symbol 50 times in one
    ticket. What we want to flag is "we keep paying for this query on
    every task we start" — that pattern only shows up across tickets.
    """
    tickets_root = klc_tickets_dir()
    if not tickets_root.exists():
        sys.stderr.write("serena_deny: no tickets directory — nothing to propose\n")
        return 0

    per_query_tickets: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    per_query_count: Counter = Counter()

    for log_path in tickets_root.glob("*/serena-calls.log"):
        ticket_id = log_path.parent.name
        for rec in _iter_log_records(log_path):
            op = rec.get("op") or ""
            subject = rec.get("subject") or ""
            key = (op, subject)
            per_query_tickets[key].add(ticket_id)
            per_query_count[key] += 1

    min_tickets = max(1, args.min_tickets)
    candidates = [
        (op, subject, len(tickets), per_query_count[(op, subject)])
        for (op, subject), tickets in per_query_tickets.items()
        if len(tickets) >= min_tickets
    ]
    candidates.sort(key=lambda row: (-row[2], -row[3], row[0], row[1]))

    # Filter out entries already covered by the effective denylist —
    # no point proposing what is already blocked.
    effective = _effective_entries()
    already: list[re.Pattern] = []
    for e in effective:
        try:
            already.append(re.compile(e["pattern"]))
        except re.error:
            continue

    def _covered(op: str, subject: str) -> bool:
        haystack = f"{op} {subject}"
        return any(p.search(haystack) for p in already)

    out_lines: list[str] = []
    today = _dt.date.today().isoformat()
    for op, subject, n_tickets, total in candidates[: args.top]:
        if _covered(op, subject):
            continue
        pattern = re.escape(op) + r"\s+" + re.escape(subject)
        out_lines.append(
            f"# seen in {n_tickets} ticket(s), {total} call(s)\n"
            f"- pattern: {_yaml_escape(pattern)}\n"
            f"  reason:  \"recurs across tickets; confirm noise before enabling\"\n"
            f"  added:   {today}"
        )

    if not out_lines:
        print("# no candidates — no query recurred across "
              f"{min_tickets}+ tickets that isn't already in the denylist")
        return 0

    print("# serena_deny propose — review each, paste the ones that are truly noise")
    print("# into .klc/knowledge/serena-deny.yml under `entries:`")
    print()
    for block in out_lines:
        print(block)
        print()
    return 0


def _effective_entries() -> list[dict]:
    """Project denylist overrides the framework seed; we merge so
    `list` and `propose` see the whole in-force set."""
    project = _read_entries(klc_serena_deny_file())
    if project:
        return project
    return _read_entries(framework_root() / "config" / "serena-deny.yml")


# --- add ----------------------------------------------------------------------

def cmd_add(args: argparse.Namespace) -> int:
    # Validate regex before touching the file.
    try:
        re.compile(args.pattern)
    except re.error as exc:
        sys.stderr.write(f"serena_deny: invalid regex: {exc}\n")
        return 2

    path = klc_serena_deny_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_entries(path)
    if any(e.get("pattern") == args.pattern for e in existing):
        sys.stderr.write("serena_deny: pattern already present; not adding\n")
        return 1

    if not path.exists():
        path.write_text(
            "# Project-level Serena query denylist.\n"
            "# Managed via `serena_deny.py add`.\n\n"
            "entries: []\n",
            encoding="utf-8",
        )

    text = path.read_text(encoding="utf-8")
    today = _dt.date.today().isoformat()
    block = (
        f"\n- pattern: {_yaml_escape(args.pattern)}\n"
        f"  reason:  {_yaml_escape(args.reason)}\n"
        f"  added:   {today}\n"
    )
    # The file may have been bootstrapped as `entries: []`; replace
    # with a sequence start the first time a real entry lands.
    if re.search(r"^entries:\s*\[\s*\]", text, flags=re.MULTILINE):
        text = re.sub(r"^entries:\s*\[\s*\]", "entries:", text, count=1,
                      flags=re.MULTILINE)
    if not re.search(r"^entries:", text, flags=re.MULTILINE):
        text = text.rstrip() + "\n\nentries:\n"
    text = text.rstrip() + block
    path.write_text(text, encoding="utf-8")
    print(f"ADDED {path}")
    return 0


# --- list / show-log ----------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    entries = _effective_entries()
    if args.json:
        json.dump(entries, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if not entries:
        print("(denylist is empty — see framework/config/serena-deny.yml for the seed)")
        return 0
    for e in entries:
        print(f"- pattern: {e.get('pattern')}")
        if e.get("reason"):
            print(f"  reason:  {e['reason']}")
        if e.get("added"):
            print(f"  added:   {e['added']}")
    return 0


def cmd_show_log(args: argparse.Namespace) -> int:
    log_path = klc_tickets_dir() / args.ticket / "serena-calls.log"
    if not log_path.exists():
        sys.stderr.write(f"serena_deny: no log at {log_path}\n")
        return 1
    events = set(args.events.split(",")) if args.events else None
    for rec in _iter_log_records(log_path):
        if events and rec.get("event") not in events:
            continue
        print(json.dumps(rec, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_p = sub.add_parser("propose",
                         help="suggest denylist entries from the call log")
    p_p.add_argument("--min-tickets", type=int, default=2,
                     help="minimum distinct tickets a query must appear in "
                          "before it qualifies as a candidate (default 2)")
    p_p.add_argument("--top", type=int, default=10,
                     help="cap on suggestions (default 10)")
    p_p.set_defaults(func=cmd_propose)

    p_a = sub.add_parser("add", help="append a validated entry to the project denylist")
    p_a.add_argument("--pattern", required=True)
    p_a.add_argument("--reason",  required=True)
    p_a.set_defaults(func=cmd_add)

    p_l = sub.add_parser("list", help="print the effective denylist")
    p_l.add_argument("--json", action="store_true", help="output JSON instead of text")
    p_l.set_defaults(func=cmd_list)

    p_s = sub.add_parser("show-log", help="tail a ticket's serena-calls.log")
    p_s.add_argument("--ticket", required=True)
    p_s.add_argument("--events", default=None,
                     help="comma-separated events to include, e.g. "
                          "'allowed,denied-pattern'")
    p_s.set_defaults(func=cmd_show_log)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
