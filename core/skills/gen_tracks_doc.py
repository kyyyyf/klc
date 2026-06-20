"""Generate config-derived regions of docs/tracks.md from source-of-truth config.

Run with --write to update the file, or without args to check for drift.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_FW_ROOT))

from core.skills.track_classifier import TRACK_THRESHOLDS  # noqa: E402
from core.skills.phases import load_phases                 # noqa: E402

REGION_THRESHOLDS = "tracks-thresholds"
REGION_SEQUENCES  = "tracks-phase-sequences"
DOC_PATH = _FW_ROOT / "docs" / "tracks.md"


def render_thresholds_table() -> str:
    """Markdown table of Track | Max total from TRACK_THRESHOLDS."""
    rows = ["| Track | Max total |", "| ----- | --------- |"]
    for name, hi in TRACK_THRESHOLDS:
        cell = str(hi) if hi is not None else "unbounded (≥9)"
        rows.append(f"| {name} | {cell} |")
    return "\n".join(rows)


def render_phase_sequences() -> str:
    """For each track in (XS,S,M,L): '**<track>**: a → b → c'."""
    phases = load_phases()
    lines = []
    for track, _ in TRACK_THRESHOLDS:
        seq = [p.id for p in phases.track_phases(track)]
        lines.append(f"**{track}**: {' → '.join(seq)}")
    return "\n\n".join(lines)


def render_region(region_id: str) -> str:
    return {
        REGION_THRESHOLDS: render_thresholds_table,
        REGION_SEQUENCES:  render_phase_sequences,
    }[region_id]()


def _replace_region(doc: str, region_id: str, body: str) -> str:
    """Replace text between GENERATED markers; append if absent."""
    begin = f"<!-- BEGIN GENERATED:{region_id} -->"
    end   = f"<!-- END GENERATED:{region_id} -->"
    block = f"{begin}\n{body.strip()}\n{end}"
    pat = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    return pat.sub(block, doc) if begin in doc else doc.rstrip() + "\n\n" + block + "\n"


def apply(doc: str) -> str:
    doc = _replace_region(doc, REGION_THRESHOLDS, render_region(REGION_THRESHOLDS))
    doc = _replace_region(doc, REGION_SEQUENCES,  render_region(REGION_SEQUENCES))
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate docs/tracks.md config regions")
    ap.add_argument("--write", action="store_true", help="Write changes to docs/tracks.md")
    args = ap.parse_args()
    cur = DOC_PATH.read_text(encoding="utf-8")
    new = apply(cur)
    if args.write:
        DOC_PATH.write_text(new, encoding="utf-8")
        print("wrote", DOC_PATH)
        return 0
    if new != cur:
        print("DRIFT: docs/tracks.md generated regions are stale; run --write")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
