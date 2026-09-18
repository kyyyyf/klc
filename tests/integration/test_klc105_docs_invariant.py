"""KLC-105 step-6 — the single-universe invariant is recorded in docs/architecture.md
(AC-10)."""
from __future__ import annotations

from pathlib import Path

_repo_root = Path(__file__).resolve().parents[2]
_doc = _repo_root / "docs" / "architecture.md"


def test_architecture_doc_states_single_universe_invariant():
    """AC-10: the Cross-cutting invariants section names files_rel as the single
    file universe for index builders AND states that a file is invisible to the
    index until git add."""
    text = _doc.read_text(encoding="utf-8")
    marker = "## Cross-cutting invariants"
    assert marker in text, "docs/architecture.md has no Cross-cutting invariants section"
    start = text.index(marker)
    end = text.index("\n---", start)
    section = text[start:end]

    assert "files_rel" in section, "section does not name files_rel"
    assert "one file universe" in section.lower() or "single" in section.lower()
    assert "git add" in section, (
        "section does not state the cost: a file is invisible to the index "
        "until git add")
