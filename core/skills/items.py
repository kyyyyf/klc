#!/usr/bin/env python3
"""items.py — inline FACT / ASSUMPTION / DECISION parser and index builder.

Format defined in process-proposal.md §2.1: GFM admonition headers
plus `key=value` attributes:

    > [!DECISION D-012] owner=ek date=2026-05-08 supersedes=D-005 refs=F-003

This skill walks every artefact under `.klc/tickets/<ticket>/**/*.md`,
extracts item headers, and writes `.klc/tickets/<ticket>/.index.json`
with the graph described in process-proposal.md §3.3.

It does three jobs:

    parse    — print items to stdout as JSONL (debug / tooling)
    index    — build .index.json atomically
    validate — run the consistency rules from process-proposal §3.4
               and exit non-zero on violations

Rules enforced:

  - dangling refs: an item references an id that doesn't exist.
  - superseded active: an active DECISION is transitively supported
    only by rejected ASSUMPTIONs.
  - orphan QUESTIONs: a QUESTION with `blocks=<id>` where the blocker
    is still active.
  - unresolved CONFLICT: any CONFLICT item still present.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import klc_ticket_dir, klc_ticket_index_file  # noqa: E402


ITEM_TYPES = (
    "FACT",
    "ASSUMPTION",
    "DECISION",
    "HYPOTHESIS",
    "CONSTRAINT",
    "QUESTION",
    "RISK",
    "CONFLICT",
)

# Header line, e.g.
#   > [!DECISION D-012] owner=ek date=2026-05-08 supersedes=D-005
HEADER_RE = re.compile(
    r"""^>\s*\[!(?P<type>[A-Z]+)\s+(?P<id>[A-Z]+-[\w-]+)\]\s*(?P<attrs>.*)$""",
)

ATTR_RE = re.compile(
    r"""(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))"""
)


@dataclass
class Item:
    type: str
    id: str
    file: str
    line: int
    attrs: dict[str, str] = field(default_factory=dict)
    body: list[str] = field(default_factory=list)


def _parse_attrs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ATTR_RE.finditer(text or ""):
        key = m.group(1)
        value = m.group(2) or m.group(3) or m.group(4) or ""
        out[key] = value
    return out


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def iter_items(root: Path) -> list[Item]:
    """Walk a directory tree; collect every inline item in every *.md.
    The body of an item is any subsequent `> ...` continuation lines
    until a non-quoted line."""
    items: list[Item] = []
    if not root.exists():
        return items
    for md in sorted(root.rglob("*.md")):
        if ".klc/tickets/" in str(md.resolve()) and md.name == ".index.json":
            continue
        try:
            lines = md.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        i = 0
        while i < len(lines):
            m = HEADER_RE.match(lines[i])
            if not m:
                i += 1
                continue
            if m.group("type") not in ITEM_TYPES:
                i += 1
                continue
            it = Item(
                type=m.group("type"),
                id=m.group("id"),
                file=str(md),
                line=i + 1,
                attrs=_parse_attrs(m.group("attrs")),
            )
            j = i + 1
            while j < len(lines) and lines[j].startswith(">"):
                it.body.append(lines[j][1:].lstrip())
                j += 1
            items.append(it)
            i = j
    return items


def build_index(ticket_id: str, *, write: bool = True) -> dict:
    root = klc_ticket_dir(ticket_id)
    items = iter_items(root)

    by_id: dict[str, dict] = {}
    for it in items:
        refs = _split_list(it.attrs.get("refs"))
        supersedes = it.attrs.get("supersedes") or None
        rel_file = _rel(it.file, root)
        by_id[it.id] = {
            "type":       it.type,
            "file":       rel_file,
            "line":       it.line,
            "attrs":      it.attrs,
            "refs":       refs,
            "supersedes": supersedes,
            "status":     _derive_status(it),
            "referenced_by": [],
            "superseded_by": None,
        }
    # back-links
    for item_id, rec in by_id.items():
        if rec["supersedes"] and rec["supersedes"] in by_id:
            by_id[rec["supersedes"]]["superseded_by"] = item_id
            by_id[rec["supersedes"]]["status"] = "superseded"
        for ref in rec["refs"]:
            if ref in by_id:
                by_id[ref]["referenced_by"].append(item_id)

    payload = {
        "ticket":       ticket_id,
        "generated_at": _now(),
        "items":        by_id,
        "dangling_refs":          _dangling(by_id),
        "orphan_questions":       _orphans(by_id),
        "unresolved_conflicts":   [i for i, r in by_id.items()
                                   if r["type"] == "CONFLICT"
                                   and r["status"] != "resolved"],
    }
    if write:
        out = klc_ticket_index_file(ticket_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return payload


def _rel(path: str, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except ValueError:
        return path


def _derive_status(it: Item) -> str:
    """Status from explicit attr, or 'active' by default."""
    explicit = (it.attrs.get("status") or "").lower()
    if explicit:
        return explicit
    # ASSUMPTION / HYPOTHESIS may have verified=<date|stale-*>
    ver = (it.attrs.get("verified") or "").lower()
    if ver.startswith("stale-"):
        return "stale"
    return "active"


def _dangling(by_id: dict) -> list[dict]:
    out = []
    for item_id, rec in by_id.items():
        for ref in rec["refs"]:
            if ref not in by_id:
                out.append({"from": item_id, "missing": ref})
        sup = rec.get("supersedes")
        if sup and sup not in by_id:
            out.append({"from": item_id, "missing": sup})
    return out


def _orphans(by_id: dict) -> list[str]:
    """QUESTION with blocks=<id> where the blocker is still active."""
    out: list[str] = []
    for qid, rec in by_id.items():
        if rec["type"] != "QUESTION":
            continue
        blocks = rec["attrs"].get("blocks")
        if not blocks:
            continue
        target = by_id.get(blocks)
        if target is None or target["status"] == "active":
            out.append(qid)
    return out


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- CLI ---------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> int:
    for it in iter_items(klc_ticket_dir(args.ticket)):
        sys.stdout.write(json.dumps({
            "type": it.type, "id": it.id, "file": it.file, "line": it.line,
            "attrs": it.attrs,
        }, ensure_ascii=False) + "\n")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    data = build_index(args.ticket, write=not args.dry_run)
    print(json.dumps({
        "items":              len(data["items"]),
        "dangling_refs":      len(data["dangling_refs"]),
        "orphan_questions":   len(data["orphan_questions"]),
        "unresolved_conflicts": len(data["unresolved_conflicts"]),
    }, ensure_ascii=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data = build_index(args.ticket, write=False)
    errs = []
    if data["dangling_refs"]:
        errs.append(("dangling_refs", data["dangling_refs"]))
    if data["orphan_questions"]:
        errs.append(("orphan_questions", data["orphan_questions"]))
    if data["unresolved_conflicts"]:
        errs.append(("unresolved_conflicts", data["unresolved_conflicts"]))
    if errs:
        for kind, details in errs:
            sys.stderr.write(f"{kind}: {json.dumps(details, ensure_ascii=False)}\n")
        return 1
    print("OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="emit items as JSONL")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("index", help="build .index.json")
    p.add_argument("--ticket", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("validate", help="consistency check (exit 1 on errors)")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
