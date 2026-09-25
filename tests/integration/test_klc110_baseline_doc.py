"""tests/integration/test_klc110_baseline_doc.py — KLC-110 step-7: the
rendered backfill table is committed under docs/ as the pre-KLC-108 baseline
(AC-18)."""
from __future__ import annotations

from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_BASELINE_DOC = _FW_ROOT / "docs" / "20260920_klc110-retrieval-baseline.md"


def test_baseline_table_committed_under_docs_with_date_index_generation_and_availability_counts():
    """AC-18: the rendered baseline table is committed under docs/ as the
    pre-KLC-108 baseline, stating its date, the index generation it was
    measured against, and its availability counts, so KLC-108 re-runs the
    same command and diffs its result against a recorded number rather than
    an impression."""
    assert _BASELINE_DOC.exists(), (
        f"{_BASELINE_DOC} not found — commit the rendered `--backfill` table")
    text = _BASELINE_DOC.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "index generation" in lowered
    assert "measured" in lowered
    assert "scored" in lowered and "unavailable" in lowered
    # KLC-108's like-for-like reference point and the pre-KLC-108 historical figure.
    assert "0.2414" in text
    assert "0.1964" in text
    # The spec-pinned three-ticket probe number is explicitly NOT used as a baseline.
    assert "0.1333" in text
