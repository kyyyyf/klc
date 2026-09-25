"""tests/integration/test_klc110_jsonl_log.py — KLC-110 step-4: the derived,
append-only cross-ticket evidence log (AC-9)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402


def test_persisting_ack_appends_one_jsonl_line_with_required_fields(tmp_path, monkeypatch):
    """AC-9: one JSON object per line, carrying the ticket key, the track,
    the trace's status/confidence, the record's own status, every computed
    metric and a UTC timestamp."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    rec = _reval.evaluate(
        {"status": "ok", "confidence": "high", "files_likely_to_edit": ["a.py"]},
        set(), {"a.py"})
    _reval.append_log("KLC-Q", "M", rec)

    rows = _reval.read_log()
    assert "KLC-Q" in rows
    row = rows["KLC-Q"]
    for key in ("ticket", "track", "trace_status", "status", "logged_at", "confidence"):
        assert key in row, row
    assert row["status"] == "ok"
    assert row["track"] == "M"


def test_second_ack_on_same_ticket_supersedes_not_duplicates(tmp_path, monkeypatch):
    """Edge case (AC-9): two persisting acks on the same ticket write two
    physical lines, but a reader keyed by ticket uses only the last one, so
    no aggregate counts the ticket twice."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.shared.paths import klc_knowledge_dir

    rec1 = _reval.evaluate(
        {"status": "ok", "confidence": "high", "files_likely_to_edit": []},
        set(), {"a.py"})
    rec2 = _reval.evaluate(
        {"status": "ok", "confidence": "high", "files_likely_to_edit": ["a.py"]},
        set(), {"a.py"})
    _reval.append_log("KLC-Q", "M", rec1)
    _reval.append_log("KLC-Q", "M", rec2)

    lines = (klc_knowledge_dir() / "retrieval-eval.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 2, lines  # two physical lines

    rows = _reval.read_log()
    assert len(rows) == 1  # superseded by ticket key on read
    assert rows["KLC-Q"]["files_likely_to_edit"]["precision"] == 1.0
