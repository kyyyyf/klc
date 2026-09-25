"""tests/integration/test_klc110_degrade_matrix.py — KLC-110 step-3: every
case that must degrade to `status: unavailable` plus a stated reason, and
must never be scored as a numeric zero (AC-11)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402


def test_degrade_matrix_records_unavailable_status_with_reason_never_zero():
    """AC-11: the record is a status of unavailable plus a stated reason,
    with no numeric metric populated, whenever the trace is absent or
    unreadable, the trace's own status is not ok, or the diff is empty
    after the .klc/ exclusion."""
    no_trace = _reval.evaluate(None, set(), {"a.py"})
    assert no_trace["status"] == "unavailable"
    assert "reason" in no_trace
    assert "precision" not in no_trace
    assert "files_likely_to_edit" not in no_trace

    bad_status = _reval.evaluate({"status": "unavailable"}, set(), {"a.py"})
    assert bad_status["status"] == "unavailable"
    assert "reason" in bad_status
    assert "files_likely_to_edit" not in bad_status

    empty_diff = _reval.evaluate(
        {"status": "ok", "files_likely_to_edit": ["a.py"]}, set(), set())
    assert empty_diff["status"] == "unavailable"
    assert "reason" in empty_diff
    assert "files_likely_to_edit" not in empty_diff


def test_no_merge_base_degrades_not_zero():
    """AC-11 / AC-7 boundary: `_committed()` returning (set(), set()) — the
    no-merge-base / shallow-clone case — degrades the whole record rather
    than scoring a 0-recall."""
    trace = {"status": "ok", "files_likely_to_edit": ["a.py"], "confidence": "high"}
    rec = _reval.evaluate(trace, set(), set())
    assert rec["status"] == "unavailable"
    assert "files_likely_to_edit" not in rec
