"""KLC-128 step-3 — AC-6: the drift check and the retrieval evaluator receive
the IDENTICAL file set at the integrate ack on a merged ticket, closing the
'two different rules' defect (spec F-003/F-004)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _merge,
    _run_ack,
    _seed_ticket,
    _set_phase,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]

_OK_TRACE = {"status": "ok", "confidence": "medium", "mode": "deterministic",
            "degraded_inputs": [], "files_likely_to_edit": ["widgets/thing.py"],
            "files_to_read_first": [], "tests_to_read_or_run": [],
            "affected_modules_hint": ["widgets"]}


def test_drift_scope_and_retrieval_receive_the_identical_file_set_on_a_merged_ticket(
    tmp_path, monkeypatch
):
    """AC-6: on a merged ticket with a recorded range, the drift check's
    scope section is computed from the SAME file set the retrieval evaluator
    scores — captured directly at the seam each brick calls through (never a
    stub returning canned data — a real passthrough that still delegates to
    the real function), plus a check on the persisted drift report."""
    import drift_check as _dc
    import retrieval_eval as _reval

    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-916"
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

    seen: dict = {}
    real_scope_compare = _dc._scope_compare

    def _wrapped_scope_compare(t, *, changed_files=None):
        seen["drift_changed_files"] = changed_files
        return real_scope_compare(t, changed_files=changed_files)

    monkeypatch.setattr(_dc, "_scope_compare", _wrapped_scope_compare)

    real_consume = _reval.consume

    def _wrapped_consume(t, trace, committed_modules, committed_paths, track, *, persist,
                         modules_data=None, ground_truth=None):
        seen["reval_committed_paths"] = set(committed_paths)
        return real_consume(t, trace, committed_modules, committed_paths, track,
                           persist=persist, modules_data=modules_data, ground_truth=ground_truth)

    monkeypatch.setattr(_reval, "consume", _wrapped_consume)

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    assert seen.get("drift_changed_files") is not None, "the drift check must receive an injected file set"
    assert set(seen["drift_changed_files"]) == seen["reval_committed_paths"]
    assert seen["reval_committed_paths"] == {"widgets/thing.py"}

    report = json.loads((tdir / "drift-report.json").read_text(encoding="utf-8"))
    assert report["scope_drift"]["skipped"] is None, \
        "a merged ticket with a recorded range must get a REAL drift result, not skipped"
