#!/usr/bin/env python3
"""`klc board` — kanban view of every live ticket.

Groups `.klc/tickets/<key>/meta.json` by phase and prints a table.
Archived tickets are omitted.
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


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc board")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

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
