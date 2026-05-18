#!/usr/bin/env python3
"""items_verify.py — periodic re-verification of FACT / ASSUMPTION /
HYPOTHESIS items in artefacts.

Inline items in ticket artefacts carry a `verified=<ISO-date>`
attribute on their header, per `process-proposal.md` §2.1. An
assertion captured in May may be wrong in November: code moved,
behaviour changed, the invariant it claimed no longer holds. This
skill catches that across all three types.

Deterministic layer (what this script does):

  - Walks FACT headers in every artefact under `.klc/tickets/**/*.md`
    (or a caller-selected subset).
  - Classifies each item:
      * `confirmed`  — `src` points at a file:line whose content did not
                       change since `verified`. Refresh the date.
      * `needs-review` — the referenced file has changed; a human or LLM
                       must decide whether the claim still holds. The
                       header gets `verified=stale-YYYY-MM-DD` appended
                       so it is visible in diffs.
      * `undecidable` — no parseable `src`, or the file is gone. Logged,
                       header untouched.
  - Appends one JSONL record per item to
    `.klc/knowledge/verification-log.jsonl`.

What this script does NOT do:

  - Content-level reasoning. A confirmed signature that still compiles
    but now means something else looks confirmed to the parser. That is
    why `needs-review` is a candidate list, not a hard verdict — an
    LLM pass reads the log and marks items rejected/verified.

Subcommands:

    scan    — inspect items, classify, optionally rewrite headers
    stats   — print summary of the latest log tail (run counts by verdict)

Usage:

    items_verify.py scan [--ticket TICK-123] [--top N]
                         [--dry-run] [--since YYYY-MM-DD]
    items_verify.py stats [--last N]

Defaults:

  - `--top 20` inspects the 20 oldest `verified=` dates across all
    tickets. The point is to keep the verification workload bounded on
    large knowledge bases — one run should not melt CI.
  - `--dry-run` classifies but does not rewrite headers; always safe.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import (  # noqa: E402
    klc_tickets_dir,
    klc_verification_log,
    project_root,
)

HEADER_RE = re.compile(
    # Accept FACT, ASSUMPTION, HYPOTHESIS — all three have `verified=`
    # and `src=` in the proposal; the verification loop is identical.
    # IDs are the authoring convention (F-001, A-007, H-002) but we
    # accept any alnum/dash token to stay robust against hand-edited
    # tickets.
    r"""^>\s*\[!(?P<type>FACT|ASSUMPTION|HYPOTHESIS)\s+(?P<id>[A-Z]+-[\w-]+)\]\s*(?P<attrs>.*)$""",
    re.IGNORECASE,
)
# Matches key=value pairs where the value is either a quoted string or a
# bare token (no whitespace). Multiple pairs per line.
ATTR_RE = re.compile(r"""(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""")
# src=path/to/file.ext:42 — we match "(…file-ish…)(:line)?"
SRC_FILE_LINE_RE = re.compile(r"^([^\s:]+?)(?::(\d+))?$")


@dataclass
class FactItem:
    id: str
    type: str             # FACT | ASSUMPTION | HYPOTHESIS
    file: Path
    lineno: int          # 1-based line number of the header in `file`
    raw_header: str
    attrs: dict[str, str] = field(default_factory=dict)


def _parse_attrs(attrs_str: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ATTR_RE.finditer(attrs_str):
        key = m.group(1)
        value = m.group(2) or m.group(3) or m.group(4) or ""
        out[key] = value
    return out


def iter_facts(root: Path) -> list[FactItem]:
    items: list[FactItem] = []
    if not root.exists():
        return items
    for md_path in root.rglob("*.md"):
        try:
            lines = md_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            m = HEADER_RE.match(line)
            if not m:
                continue
            items.append(FactItem(
                id=m.group("id"),
                type=m.group("type").upper(),
                file=md_path,
                lineno=i,
                raw_header=line,
                attrs=_parse_attrs(m.group("attrs") or ""),
            ))
    return items


def _git_log_touched(repo: Path, file: str, since_iso: str) -> bool:
    """Return True if `file` was touched AFTER `since_iso` (exclusive).

    `since_iso` is the `verified=` date (YYYY-MM-DD). We rely on author
    date (`%ad`) rather than `--since`, which keys off committer date.
    The distinction matters in rebased/cherry-picked histories and in
    tests that set `GIT_AUTHOR_DATE` — committer date stays "today"
    while the semantic date of the change is the author date.

    Returns True iff any commit touching `file` has author date strictly
    greater than `since_iso`. If the date is malformed or git is
    unreachable, returns False (caller treats that as not-drifted).
    """
    if not file:
        return False
    try:
        boundary = _dt.date.fromisoformat(since_iso)
    except ValueError:
        return False
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "log",
             "--date=short", "--pretty=format:%ad",
             "--", file],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in r.stdout.splitlines():
        try:
            d = _dt.date.fromisoformat(line.strip())
        except ValueError:
            continue
        if d > boundary:
            return True
    return False


def _file_exists(repo: Path, file: str) -> bool:
    if not file:
        return False
    return (repo / file).exists()


def classify(item: FactItem, repo: Path) -> tuple[str, str, str | None]:
    """Return (verdict, reason, new_verified).

    verdict ∈ {confirmed, needs-review, undecidable}. `new_verified` is
    the replacement for the `verified=` attribute (None means leave the
    header untouched)."""
    src = item.attrs.get("src", "").strip()
    verified = item.attrs.get("verified", "").strip()
    if not src:
        return "undecidable", "no src attribute", None
    if not verified:
        return "undecidable", "no verified attribute", None

    m = SRC_FILE_LINE_RE.match(src)
    if not m:
        # src might reference a metric, a commit SHA, or a URL — we
        # can't mechanically re-verify those. Leave them for the LLM
        # layer.
        return "undecidable", f"src not file:line ({src!r})", None
    file, _line = m.group(1), m.group(2)

    if not _file_exists(repo, file):
        return "needs-review", f"file disappeared: {file}", f"stale-{_today()}"

    changed = _git_log_touched(repo, file, verified)
    if changed:
        return "needs-review", f"{file} touched since {verified}", f"stale-{_today()}"
    return "confirmed", "src unchanged since verified", _today()


def _today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _replace_verified(raw_header: str, new_value: str) -> str:
    """Rewrite the `verified=` attribute in the header line. If the
    attribute is absent, append it. Quotes are preserved when present."""
    def _sub(m: re.Match[str]) -> str:
        return f"verified={new_value}"
    if re.search(r"verified\s*=\s*\S+", raw_header):
        return re.sub(r"verified\s*=\s*\S+", _sub, raw_header, count=1)
    # Append before a possible trailing "]" — here headers end in plain
    # text after the ID bracket, so just append at end.
    return raw_header.rstrip() + f" verified={new_value}"


def _rewrite(item: FactItem, new_verified: str) -> None:
    text = item.file.read_text(encoding="utf-8")
    lines = text.splitlines()
    idx = item.lineno - 1
    if idx < 0 or idx >= len(lines):
        return
    lines[idx] = _replace_verified(lines[idx], new_verified)
    item.file.write_text(
        "\n".join(lines) + ("\n" if text.endswith("\n") else ""),
        encoding="utf-8",
    )


def _write_log(entries: list[dict]) -> None:
    log_path = klc_verification_log()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_scan(args: argparse.Namespace) -> int:
    root = klc_tickets_dir()
    if args.ticket:
        root = root / args.ticket
    items = iter_facts(root)

    # Age-prioritise: oldest `verified=` first. Items without a parseable
    # date sort to the front (caller sees them as the most urgent).
    def _age_key(it: FactItem) -> str:
        v = it.attrs.get("verified", "")
        if v.startswith("stale-"):
            v = v[6:]
        return v or "0000-00-00"

    items.sort(key=_age_key)
    if args.top and args.top > 0:
        items = items[: args.top]

    if args.since:
        items = [it for it in items if _age_key(it) < args.since]

    repo = project_root()
    log_entries: list[dict] = []
    counts = {"confirmed": 0, "needs-review": 0, "undecidable": 0}
    now = _now_iso()

    for it in items:
        verdict, reason, new_verified = classify(it, repo)
        counts[verdict] += 1
        log_entries.append({
            "t":        now,
            "id":       it.id,
            "type":     it.type,
            "file":     str(it.file.relative_to(project_root())),
            "line":     it.lineno,
            "src":      it.attrs.get("src"),
            "was_verified": it.attrs.get("verified"),
            "verdict":  verdict,
            "reason":   reason,
            "rewrote":  bool(new_verified) and not args.dry_run,
        })
        if new_verified and not args.dry_run:
            _rewrite(it, new_verified)

    if log_entries:
        _write_log(log_entries)

    summary = {
        "inspected": len(log_entries),
        "counts":    counts,
        "dry_run":   bool(args.dry_run),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    log_path = klc_verification_log()
    if not log_path.exists():
        print(json.dumps({"runs": 0, "counts": {}}))
        return 0
    # Tail the last N records.
    lines = log_path.read_text(encoding="utf-8").splitlines()
    if args.last > 0:
        lines = lines[-args.last:]
    counts = {"confirmed": 0, "needs-review": 0, "undecidable": 0}
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        v = rec.get("verdict")
        if v in counts:
            counts[v] += 1
    print(json.dumps({"runs": len(lines), "counts": counts}, ensure_ascii=False))
    return 0


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_s = sub.add_parser("scan", help="classify FACT items, optionally rewrite headers")
    p_s.add_argument("--ticket", default=None,
                     help="limit to one ticket's artefacts (default: all)")
    p_s.add_argument("--top", type=int, default=20,
                     help="number of oldest items to inspect (default 20, 0 = all)")
    p_s.add_argument("--since", default=None,
                     help="only consider items verified before this ISO date")
    p_s.add_argument("--dry-run", action="store_true",
                     help="classify and log but do not rewrite any header")
    p_s.set_defaults(func=cmd_scan)

    p_t = sub.add_parser("stats", help="summary of the latest log tail")
    p_t.add_argument("--last", type=int, default=200,
                     help="inspect the last N log records (default 200)")
    p_t.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
