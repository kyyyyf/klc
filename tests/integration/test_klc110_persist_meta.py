"""tests/integration/test_klc110_persist_meta.py — KLC-110 step-4: the
persisting ack path writes the complete record into
meta.json:metrics.retrieval, through the same staged-meta-patch seam step-2
built (AC-8)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle as _lc  # noqa: E402
import retrieval_eval as _reval  # noqa: E402


def test_persisting_ack_logs_retrieval_row_and_compact_meta_record(tmp_path, monkeypatch):
    """AC-8: the evaluator logs the complete record into the
    derived retrieval-eval.jsonl (not meta.json, KLC-176) on the persisting integrate-ack path only."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc" / "tickets" / "KLC-Z"
    d.mkdir(parents=True)
    meta_path = d / "meta.json"
    meta_path.write_text(
        json.dumps({"phase": "integrate:work", "track": "M", "metrics": {}}),
        encoding="utf-8")

    trace = {"status": "ok", "confidence": "medium",
             "files_likely_to_edit": ["a.py"], "files_to_read_first": [],
             "tests_to_read_or_run": [], "affected_modules_hint": []}
    rec = _reval.consume("KLC-Z", trace, set(), {"a.py"}, "M", persist=True)
    _lc.set_state("KLC-Z", "integrate", "ack-needed")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # KLC-176: the record is no longer copied into meta.json; the derived row has it
    # KLC-176 (review F-002): a COMPACT record stays in meta so every clone sees
    # it; the full record lives in the jsonl log.
    assert set(meta["metrics"]["retrieval"]) == {"score", "confidence", "at"}
    assert _reval.logged_record("KLC-Z")["status"] == rec["status"] == "ok"


def test_degraded_inputs_copied_through_when_present_omitted_otherwise():
    """Q-004: KLC-106's degraded_inputs field is copied through verbatim
    when the trace carries it, and omitted otherwise."""
    with_field = _reval.evaluate(
        {"status": "ok", "degraded_inputs": ["file_roles.json"],
         "files_likely_to_edit": ["a.py"]}, set(), {"a.py"})
    assert with_field["degraded_inputs"] == ["file_roles.json"]

    without_field = _reval.evaluate(
        {"status": "ok", "files_likely_to_edit": ["a.py"]}, set(), {"a.py"})
    assert "degraded_inputs" not in without_field
