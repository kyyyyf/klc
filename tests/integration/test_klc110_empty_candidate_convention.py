"""tests/integration/test_klc110_empty_candidate_convention.py — KLC-110
step-1: an empty candidate list on an otherwise usable trace must never be
scored as a perfect (1.0) match through the empty-set convention (AC-6)."""
from __future__ import annotations

import sys
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "core" / "skills"
if str(_SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILLS_DIR))

import retrieval_eval as _reval  # noqa: E402


def test_empty_candidate_list_records_null_precision_zero_candidates_real_recall():
    """AC-6: an empty candidate list on an otherwise usable trace records a
    null precision, a candidate count of zero, and a recall computed against
    the real ground truth — never the 1.0 empty-set convention."""
    rank_metrics = _reval.rank_metrics
    truth = {"core/skills/a.py", "core/skills/b.py"}
    result = rank_metrics([], truth, 5)
    assert result["precision"] is None
    assert result["candidates"] == 0
    assert result["recall"] == 0.0


def test_empty_tests_to_read_or_run_on_changed_tests_is_a_miss_not_1_0():
    """AC-6 (GAP-562 motivating case): an empty tests_to_read_or_run
    candidate list, scored against the changed test files, reads as a miss
    (recall 0.0) and never as the 1.0 the empty-set convention would
    otherwise award an empty set."""
    rank_metrics = _reval.rank_metrics
    test_truth = {"tests/integration/test_klc110_scorer.py"}
    result = rank_metrics([], test_truth, len(test_truth) or 1)
    assert result["recall"] == 0.0
    assert result["precision"] is None
    assert result["candidates"] == 0
