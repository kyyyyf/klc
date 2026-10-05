"""tests/integration/test_klc110_calibration_fixture.py — KLC-110 step-6:
AC-20 end-to-end — a high-confidence, zero-precision fixture flags a
calibration failure through the whole seam: the written record, the rollup's
`per_confidence.high` bucket, and the integrate-ack advisory."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle as _lc  # noqa: E402
import metrics as _metrics  # noqa: E402
import phase_completion as _pc  # noqa: E402


def _fake_git(calls):
    def _run(args, repo=None):
        calls.append(list(args))
        if args[0] == "merge-base":
            return "deadbeef"
        if args[0] == "diff":
            return "a.py\n"
        return ""
    return _run


def _write_ticket(tmp_path, key, *, edit_candidates):
    d = tmp_path / ".klc" / "tickets" / key
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"ticket": key, "phase": "integrate:work", "track": "M"}),
        encoding="utf-8")
    trace = {"status": "ok", "confidence": "high",
             "files_likely_to_edit": edit_candidates,
             "files_to_read_first": [], "tests_to_read_or_run": [],
             "affected_modules_hint": []}
    (d / "retrieval_trace.json").write_text(json.dumps(trace), encoding="utf-8")
    return d


def _persist_advisory(tmp_path, monkeypatch, key, *, edit_candidates):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_ticket(tmp_path, key, edit_candidates=edit_candidates)
    calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(calls))
    monkeypatch.setattr(_pc, "_load_modules", lambda: {"modules": []})

    recs = _pc._retrieval_advisories(key, True, committed={})

    # Flush the staged meta patch exactly as `lifecycle.set_state` would.
    meta = _lc.read_meta(key)
    _lc._apply_meta_patch(key, meta)
    _lc.write_meta(key, meta)
    return recs, meta


def _logged(root, ticket):
    """KLC-176: the record lives only in the derived retrieval-eval.jsonl."""
    rec = {}
    for line in (root / ".klc" / "knowledge" / "retrieval-eval.jsonl").read_text("utf-8").splitlines():
        row = json.loads(line)
        if row.get("ticket") == ticket:
            rec = row
    return rec


def test_high_confidence_zero_precision_fixture_flags_calibration_and_advisory(
    tmp_path, monkeypatch
):
    """AC-20: a fixture ticket whose trace declares confidence `high` while
    its `files_likely_to_edit` hits none of its changed files produces
    precision@5 of zero in `meta.json:metrics.retrieval`, its key in
    `per_confidence.high.retrieval.zero_precision_at_5_tickets`, and exactly
    one advisory line at the integrate ack."""
    recs, meta = _persist_advisory(tmp_path, monkeypatch, "KLC-CAL1",
                                   edit_candidates=["z.py"])
    assert _logged(tmp_path, "KLC-CAL1")["files_likely_to_edit"]["precision"] == 0.0
    assert len(recs) == 1
    assert recs[0]["source"] == "retrieval-eval"
    assert recs[0]["severity"] == "medium"

    (tmp_path / ".klc" / "knowledge").mkdir(parents=True, exist_ok=True)
    _metrics.cmd_rollup(argparse.Namespace(output=None))
    data = json.loads((tmp_path / ".klc" / "knowledge" / "process-metrics.json")
                      .read_text(encoding="utf-8"))
    assert "KLC-CAL1" in data["per_confidence"]["high"]["retrieval"]["zero_precision_at_5_tickets"]


def test_matching_fixture_produces_precision_at_5_of_one(tmp_path, monkeypatch):
    """Positive e2e sibling of AC-20: a fixture ticket whose diff matches its
    trace scores precision@5 = 1.0, records no entry in
    `zero_precision_at_5_tickets`, and raises no advisory."""
    recs, meta = _persist_advisory(tmp_path, monkeypatch, "KLC-CAL2",
                                   edit_candidates=["a.py"])
    assert _logged(tmp_path, "KLC-CAL2")["files_likely_to_edit"]["precision"] == 1.0
    assert recs == []

    (tmp_path / ".klc" / "knowledge").mkdir(parents=True, exist_ok=True)
    _metrics.cmd_rollup(argparse.Namespace(output=None))
    data = json.loads((tmp_path / ".klc" / "knowledge" / "process-metrics.json")
                      .read_text(encoding="utf-8"))
    assert "KLC-CAL2" not in data["per_confidence"]["high"]["retrieval"]["zero_precision_at_5_tickets"]
