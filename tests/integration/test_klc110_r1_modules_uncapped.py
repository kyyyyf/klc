"""tests/integration/test_klc110_r1_modules_uncapped.py — KLC-110 review
round 1, step-8 (HIGH, AC-5): the `affected_modules_hint` arrow must be
scored UNCAPPED — the hint is an alphabetically sorted, unranked, uncapped
set (`planning-retriever.py`), so truncating it to `len(truth)` candidates
(the pre-fix behaviour) let a hint far larger than the truth set score a
perfect precision while `is_subset` correctly read `False` in the very same
record — an internally contradictory record."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402


def test_ac5_modules_arrow_scored_uncapped_not_truncated_to_truth_size():
    """AC-5: `affected_modules_hint` is scored against the WHOLE hint list
    (k = len(hint) or 1), never truncated to `len(truth)` — a hint of four
    modules against a truth set of one must score precision 0.25 (1 of 4),
    not the false-perfect 1.0 the pre-fix truncation produced, and `extra`
    must list every module the hint over-claimed, consistent with
    `is_subset: False` in the same record."""
    trace = {"status": "ok", "confidence": "low",
             "affected_modules_hint": ["a", "b", "c", "z"]}
    rec = _reval.evaluate(trace, {"a"}, {"dummy.py"})
    arrow = rec["affected_modules_hint"]
    assert arrow["precision"] == 0.25
    assert arrow["candidates"] == 4
    assert arrow["extra"] == ["b", "c", "z"]
    assert arrow["matched"] == ["a"]
    assert arrow["is_subset"] is False
    assert arrow["is_superset"] is True


def test_ac5_modules_arrow_still_scores_correctly_when_hint_matches_truth():
    """Regression: a hint that equals the truth set still scores a clean
    precision/recall of 1.0 after the fix (the uncapped k does not change
    the equal-size case)."""
    trace = {"status": "ok", "confidence": "low",
             "affected_modules_hint": ["a", "b"]}
    rec = _reval.evaluate(trace, {"a", "b"}, {"dummy.py"})
    arrow = rec["affected_modules_hint"]
    assert arrow["precision"] == 1.0
    assert arrow["recall"] == 1.0
    assert arrow["is_subset"] is True
    assert arrow["is_superset"] is True
