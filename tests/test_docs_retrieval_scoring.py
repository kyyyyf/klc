"""KLC-108 — AC-10 (docs half): `docs/architecture.md` states the module
scoring formula and the confidence rule in the same terms the code
implements."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "architecture.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_architecture_doc_states_module_scoring_formula():
    """AC-10: the docs page that describes retrieval states the same
    size-normalising formula the code implements."""
    text = _text()
    assert "Retrieval scoring" in text
    assert "own_signal + best_file + aggregate / sqrt(n_matched)" in text


def test_architecture_doc_states_test_module_bar():
    text = _text()
    assert "80%" in text and "primary_modules" in text


def test_architecture_doc_states_confidence_rule():
    text = _text()
    assert "_HIGH_SEPARATION_RATIO" in text
    assert "files_likely_to_edit" in text
