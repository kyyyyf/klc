"""tests/integration/test_klc110_advisory.py — KLC-110 step-5: the
calibration advisory fires only for a confidently wrong retriever (AC-15)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402


def test_advisory_line_fires_only_for_medium_or_high_confidence_zero_precision_and_points_to_doctor():
    """AC-15: the integrate ack surfaces exactly one advisory line naming
    the ticket and pointing at klc doctor when status is ok, confidence is
    medium/high, and precision@5 is zero or files_likely_to_edit was empty
    — and surfaces no such line in any other case."""
    zero_precision = _reval.evaluate(
        {"status": "ok", "confidence": "high", "files_likely_to_edit": ["z.py"]},
        set(), {"a.py"})
    recs = _reval.advisory_records("KLC-Z", zero_precision)
    assert len(recs) == 1
    assert recs[0]["severity"] == "medium"
    assert "klc doctor" in recs[0]["message"]
    assert recs[0]["ref"] == "KLC-Z"

    empty_edit = _reval.evaluate(
        {"status": "ok", "confidence": "medium", "files_likely_to_edit": []},
        set(), {"a.py"})
    recs2 = _reval.advisory_records("KLC-Z", empty_edit)
    assert len(recs2) == 1
    assert recs2[0]["severity"] == "info"
    assert "klc doctor" in recs2[0]["message"]

    hit = _reval.evaluate(
        {"status": "ok", "confidence": "high", "files_likely_to_edit": ["a.py"]},
        set(), {"a.py"})
    assert _reval.advisory_records("KLC-Z", hit) == []


def test_low_confidence_zero_precision_no_advisory():
    """AC-15 negative twin: a low-confidence trace with precision@5 == 0
    raises no advisory."""
    low_conf = _reval.evaluate(
        {"status": "ok", "confidence": "low", "files_likely_to_edit": ["z.py"]},
        set(), {"a.py"})
    assert _reval.advisory_records("KLC-Z", low_conf) == []
