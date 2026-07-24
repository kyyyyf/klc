#!/usr/bin/env python3
"""`klc board` — kanban view of every ticket.

Groups `.klc/tickets/<key>/meta.json` by the raw `phase` string and prints a
table. The terminal pseudo-states `archived` (done) and `cancelled` (terminated
early, KLC-076) each form their own section (`== archived (N) ==` /
`== cancelled (N) ==`) — never an active/pending phase section. Because board
buckets by the raw phase string and never resolves it through
`phases.by_id`/`parse_state`, an unknown or terminal phase is just a section
label and never crashes the view.

`board --epic <ROOT>` (KLC-078) is a different, epic-scoped view on the same
non-mutating read: it scans members (`meta.epic == <ROOT>`), computes the epic
state, per-member dependency status, the ready set, and validation warnings via
`epic_view`. The view code makes no write over the tickets it renders: it loads
meta.json directly (no `lifecycle.read_meta` migration write) and never advances
a phase. (Note: `board` is not in the dispatcher's `NO_DRAIN_CMDS`, so — like the
default board — invoking it still triggers the pre-existing opportunistic Jira
queue drain at the process level, a no-op when the queue is empty; a separate
follow-up could add `board` to `NO_DRAIN_CMDS`.)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_tickets_dir  # noqa: E402
import holder_display  # noqa: E402


def _load_all_metas(tdir: Path) -> dict[str, dict]:
    """Read every ticket's meta.json directly and normalize a legacy phase string
    IN MEMORY (no write — board stays read-only). Normalizing with the SAME
    `lifecycle._migrate_legacy_phase` that `read_meta_ro` uses means the epic
    dependency computation sees exactly the phase the live guard would (a legacy
    `learn` / `build-pending` resolves, not treated as malformed). Malformed json
    is skipped, never fatal."""
    import lifecycle  # noqa: E402  (skills dir already on sys.path)
    metas: dict[str, dict] = {}
    if tdir.exists():
        for meta_file in tdir.glob("*/meta.json"):
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            lifecycle._migrate_legacy_phase(m)  # in-memory only; returns bool
            key = m.get("ticket") or meta_file.parent.name
            metas[key] = m
    return metas


def _run_epic(root: str, as_json: bool) -> int:
    import epic_view  # noqa: E402  (skills dir already on sys.path)
    try:
        import identity  # noqa: E402
        me = identity.current()
    except (Exception, SystemExit):
        # identity.current() raises SystemExit (a BaseException, not Exception)
        # when no git identity / $USER is configured; catch it so the epic view
        # still renders with me=None (held-by-other fail-safe), mirroring
        # heartbeat.py. A bare `except Exception` would let it crash the view.
        me = None

    metas = _load_all_metas(klc_tickets_dir())
    report = epic_view.compute_epic(root, metas, me=me)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif not report.members:
        # Keep --json a valid, parseable shape even for an empty epic (codex P2);
        # only the human text form prints the friendly prose.
        print(f"(no epic {root}: no members with meta.epic == {root!r})")
    else:
        print(epic_view.render_text(report))
    return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc board")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--epic", metavar="ROOT",
                    help="epic-scoped view for the epic rooted at ROOT")
    args = ap.parse_args(argv)

    if args.epic:
        return _run_epic(args.epic, args.json)

    tdir = klc_tickets_dir()
    by_phase: dict[str, list[dict]] = defaultdict(list)
    if tdir.exists():
        for meta_file in tdir.glob("*/meta.json"):
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            rec = {
                "key":   m.get("ticket"),
                "track": m.get("track"),
                "kind":  m.get("kind"),
            }
            label = holder_display.holder_label(m)
            if label:  # omit the key entirely when absent/degraded (fail-closed)
                rec["holder_id"] = label
            by_phase[m.get("phase", "?")].append(rec)

    if args.json:
        print(json.dumps(by_phase, indent=2, ensure_ascii=False))
        return 0

    if not by_phase:
        print("(no tickets)")
        return 0

    for phase in sorted(by_phase):
        entries = by_phase[phase]
        print(f"== {phase} ({len(entries)}) ==")
        for e in entries:
            held = f"  held by {e['holder_id']}" if e.get("holder_id") else ""
            print(f"  {e['key']}  track={e['track'] or '?':<2}  kind={e['kind'] or '?'}{held}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
