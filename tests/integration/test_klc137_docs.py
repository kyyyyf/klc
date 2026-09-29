"""KLC-137 step-6 — AC-12: `docs/architecture.md` documents `line_end`,
`symbol_range` and `line_ranges` (Q-007: independent of the untracked maki
review file).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
_FORBIDDEN = "docs/" + "20260928_from_maki.md"   # built in two parts (Q-007)


def _section() -> str:
    text = _ARCHITECTURE.read_text(encoding="utf-8")
    start = text.index("## Symbol line ranges (KLC-137)")
    nxt = text.find("\n## ", start + 1)
    return text[start: nxt if nxt != -1 else len(text)]


def test_architecture_md_documents_line_end_line_ranges_symbol_range_staleness_and_klc139_boundary():
    """AC-12: one section states `line_end`, `line_ranges` and
    `symbol_range` together with the per-file cap (3), the strong-hit
    matching rule, the AC-9 staleness/name-on-start-line check, the
    inventory-vs-skeleton boundary (KLC-139), and names the maki review by
    title."""
    section = _section()
    for needle in ("line_end", "line_ranges", "symbol_range", "3", "strong",
                  "stale", "skeleton", "KLC-139", "maki review of 2026-09-28"):
        assert needle in section, f"missing {needle!r} in the KLC-137 docs section"


def test_docs_section_has_no_dependency_on_the_untracked_maki_file():
    """AC-12, Q-007: nothing here depends on the untracked maki file."""
    assert _FORBIDDEN not in _ARCHITECTURE.read_text(encoding="utf-8")
    assert _FORBIDDEN not in Path(__file__).read_text(encoding="utf-8")
