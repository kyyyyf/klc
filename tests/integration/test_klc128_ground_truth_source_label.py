"""KLC-128 step-3 — AC-7: the drift report and the retrieval record both
carry a `ground_truth_source` field naming which rule produced the ground
truth."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _retrieval_rec,
    _bare_and_clone,
    _branch_with_commits,
    _merge,
    _merged_no_recording,
    _capture_drift_reports,
    _last_drift_report,
    _run_ack,
    _seed_ticket,
    _set_phase,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]

_OK_TRACE = {"status": "ok", "confidence": "medium", "mode": "deterministic",
            "degraded_inputs": [], "files_likely_to_edit": ["widgets/thing.py"],
            "files_to_read_first": [], "tests_to_read_or_run": [],
            "affected_modules_hint": ["widgets"]}


def test_source_label_is_recorded_range_after_a_merge(tmp_path, monkeypatch):
    """AC-7, label 1/3: a merged ticket with a usable recorded range — both
    the drift report and the retrieval record carry
    `ground_truth_source: "recorded-range"`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-919"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "ff-only")

    tdir = clone / ".klc" / "tickets" / ticket
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")
    _set_phase(clone, ticket, "integrate:work")

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    report = _last_drift_report()
    assert report["ground_truth_source"] == "recorded-range"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert _retrieval_rec(tdir.parents[2], tdir.name)["ground_truth_source"] == "recorded-range"


def test_source_label_is_live_merge_base_when_live_diff_is_non_empty(tmp_path, monkeypatch):
    """AC-7, label 2/3: an UNMERGED ticket, live diff non-empty — this
    exercises the resolver directly (as AC-3's fixture does) rather than
    claiming an operator should ack integrate pre-merge (Non-goal / approach
    D is rejected); the label mechanism is what AC-7 requires tested. The
    staged retrieval-metrics patch is flushed through the real
    `lifecycle.set_state`, exactly as `ack.py`'s own manual-completion branch
    would."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-920"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc
    import lifecycle as _lc
    _capture_drift_reports(monkeypatch)

    ok, _msg = _pc.can_complete(ticket, "integrate", persist=True)
    assert ok is True
    _lc.set_state(ticket, "integrate", "ack-needed", event="manual-completion", note="test")

    report = _last_drift_report()
    assert report["ground_truth_source"] == "live-merge-base"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert _retrieval_rec(tdir.parents[2], tdir.name)["ground_truth_source"] == "live-merge-base"


def test_source_label_is_none_when_nothing_is_usable(tmp_path, monkeypatch):
    """AC-7, label 3/3: a merged ticket with no recorded range and an empty
    live diff — `ground_truth_source: "none"` on both records, paired with
    AC-8's degrade reason."""
    ticket = "KLC-921"
    clone = _merged_no_recording(tmp_path, ticket)

    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    report = _last_drift_report()
    assert report["ground_truth_source"] == "none"
    assert report["scope_drift"]["skipped"]
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert _retrieval_rec(tdir.parents[2], tdir.name)["ground_truth_source"] == "none"
