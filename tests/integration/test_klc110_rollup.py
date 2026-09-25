"""tests/integration/test_klc110_rollup.py — KLC-110 step-6: `klc metrics
--rollup` aggregates the retrieval records into per-track and per-confidence
blocks (AC-13, AC-14)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import metrics as _metrics  # noqa: E402


def _rec(status="ok", *, precision5=0.5, recall5=0.5, precision10=0.5,
         recall10=0.5, items_before_first=1, tests_recall=0.5,
         mod_precision=0.5, mod_recall=0.5, confidence="low",
         degraded_inputs=None):
    if status != "ok":
        return {"status": status, "reason": "fixture-degraded", "confidence": confidence}
    return {
        "status": "ok",
        "confidence": confidence,
        "degraded_inputs": degraded_inputs or [],
        "files_likely_to_edit": {"precision": precision5, "recall": recall5, "candidates": 1},
        "files_to_read_first": {"precision": precision10, "recall": recall10,
                                "items_before_first_hit": items_before_first},
        "tests_to_read_or_run": {"recall": tests_recall},
        "affected_modules_hint": {"precision": mod_precision, "recall": mod_recall,
                                  "is_subset": True, "is_superset": True},
    }


def _make_ticket(tickets_dir: Path, key: str, track: str, *,
                 retrieval=None, no_metrics=False) -> None:
    tdir = tickets_dir / key
    tdir.mkdir(parents=True)
    meta = {
        "ticket": key, "kind": "tech", "kind_source": "user", "phase": "archived",
        "phase_history": [
            {"phase": "intake:work", "started_at": "2026-06-01T00:00:00Z",
             "finished_at": "2026-06-01T00:01:00Z"},
        ],
        "track": track, "estimate": {"total": 5},
    }
    if not no_metrics:
        meta["metrics"] = {"retrieval": retrieval} if retrieval is not None else {}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _rollup(tmp_path, monkeypatch) -> dict:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / ".klc" / "knowledge").mkdir(parents=True, exist_ok=True)
    args = argparse.Namespace(output=None)
    _metrics.cmd_rollup(args)
    out_path = tmp_path / ".klc" / "knowledge" / "process-metrics.json"
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_rollup_emits_retrieval_subblock_under_per_track_ok_only(tmp_path, monkeypatch):
    """AC-13: `klc metrics --rollup` emits a `retrieval` sub-block under each
    `per_track.<track>` entry, carrying the mean of each metric and the
    counts of scored and unavailable tickets, aggregating only status:ok
    records."""
    tickets_dir = tmp_path / ".klc" / "tickets"
    _make_ticket(tickets_dir, "KLC-R1", "M", retrieval=_rec(precision5=1.0))
    _make_ticket(tickets_dir, "KLC-R2", "M", retrieval=_rec(status="unavailable"))

    data = _rollup(tmp_path, monkeypatch)
    retrieval = data["per_track"]["M"]["retrieval"]
    assert retrieval["tickets_scored"] == 1
    assert retrieval["tickets_unavailable"] == 1
    assert retrieval["precision_at_5_mean"] == 1.0


def test_rollup_emits_per_confidence_block_with_zero_precision_at_5_tickets_list(
    tmp_path, monkeypatch
):
    """AC-14: `klc metrics --rollup` emits a top-level `per_confidence` block
    keyed by `high`, `medium`, `low` and `unknown`, each holding the same
    retrieval shape plus a `zero_precision_at_5_tickets` list of ticket
    keys."""
    tickets_dir = tmp_path / ".klc" / "tickets"
    _make_ticket(tickets_dir, "KLC-C1", "M", retrieval=_rec(confidence="high", precision5=1.0))
    _make_ticket(tickets_dir, "KLC-C2", "M", retrieval=_rec(confidence="medium", precision5=0.0))
    _make_ticket(tickets_dir, "KLC-C3", "M", retrieval=_rec(confidence="low", precision5=0.2))
    _make_ticket(tickets_dir, "KLC-C4", "M", retrieval=_rec(confidence="unknown", precision5=0.3))

    data = _rollup(tmp_path, monkeypatch)
    per_conf = data["per_confidence"]
    for bucket in ("high", "medium", "low", "unknown"):
        assert bucket in per_conf, per_conf.keys()
        assert "retrieval" in per_conf[bucket]
    assert per_conf["medium"]["retrieval"]["zero_precision_at_5_tickets"] == ["KLC-C2"]


def test_high_confidence_zero_precision_ticket_appears_in_zero_precision_list(
    tmp_path, monkeypatch
):
    """Bridges AC-14 and AC-20: a high-confidence, precision@5 == 0 record
    appears under `per_confidence.high.retrieval.zero_precision_at_5_tickets`
    in the rollup, not only in the per-ack advisory."""
    tickets_dir = tmp_path / ".klc" / "tickets"
    _make_ticket(tickets_dir, "KLC-H1", "M", retrieval=_rec(confidence="high", precision5=0.0))
    _make_ticket(tickets_dir, "KLC-H2", "M", retrieval=_rec(confidence="high", precision5=1.0))

    data = _rollup(tmp_path, monkeypatch)
    zero_list = data["per_confidence"]["high"]["retrieval"]["zero_precision_at_5_tickets"]
    assert zero_list == ["KLC-H1"]


def test_existing_per_track_keys_unchanged_by_retrieval_subblock(tmp_path, monkeypatch):
    """Regression: `metrics.py --rollup`'s existing `per_track.<track>` keys
    (`tickets`, `cycle_time_sec_median`, `tokens_by_phase`,
    `cheap_escape_rate`, …) are untouched by the new `retrieval` sub-block."""
    tickets_dir = tmp_path / ".klc" / "tickets"
    _make_ticket(tickets_dir, "KLC-E1", "M", retrieval=_rec())

    data = _rollup(tmp_path, monkeypatch)
    track_block = data["per_track"]["M"]
    for key in ("tickets", "cycle_time_sec_median", "cycle_time_sec_p95",
               "rework_mean", "tokens_by_phase", "cheap_escape_rate",
               "prompt_bytes_per_ticket", "review_passes_per_ticket",
               "estimator_calibration", "retrieval"):
        assert key in track_block, f"missing existing key {key!r}"


def test_null_precision_excluded_from_mean_not_counted_as_zero(tmp_path, monkeypatch):
    """Design Q-101: a null metric (an empty candidate list, AC-6) is
    excluded from its rollup mean rather than counted as a zero, while the
    ticket still appears in `zero_precision_at_5_tickets`."""
    tickets_dir = tmp_path / ".klc" / "tickets"
    rec_null = _rec(confidence="medium")
    rec_null["files_likely_to_edit"] = {"precision": None, "recall": 0.0, "candidates": 0}
    _make_ticket(tickets_dir, "KLC-N1", "M", retrieval=rec_null)
    _make_ticket(tickets_dir, "KLC-N2", "M", retrieval=_rec(confidence="medium", precision5=1.0))

    data = _rollup(tmp_path, monkeypatch)
    retrieval = data["per_track"]["M"]["retrieval"]
    assert retrieval["precision_at_5_mean"] == 1.0
    zero_list = data["per_confidence"]["medium"]["retrieval"]["zero_precision_at_5_tickets"]
    assert "KLC-N1" in zero_list


def test_no_record_bucket_separate_from_unknown_confidence(tmp_path, monkeypatch):
    """Design D-303: `per_confidence` keeps `unknown` reserved for a trace
    that genuinely reported an unknown confidence, and gains an additive
    `no_record` bucket for a ticket carrying no `metrics.retrieval` key at
    all — membership decided by the key's presence, not by a confidence
    lookup."""
    tickets_dir = tmp_path / ".klc" / "tickets"
    _make_ticket(tickets_dir, "KLC-U1", "M", retrieval=_rec(confidence="unknown"))
    _make_ticket(tickets_dir, "KLC-U2", "XS")   # never measured: no metrics.retrieval key

    data = _rollup(tmp_path, monkeypatch)
    per_conf = data["per_confidence"]
    assert per_conf["unknown"]["tickets"] == 1
    assert per_conf["no_record"]["tickets"] == 1
