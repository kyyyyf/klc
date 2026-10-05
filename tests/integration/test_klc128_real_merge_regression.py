"""KLC-128 step-3 — AC-11: the KLC-110-retro regression test (F-016). A fresh
fixture repo, real commits on a ticket branch, a real `git merge --ff-only`,
a real `git push` to a bare `origin`, THEN the integrate ack runs. This is the
literal regression KLC-110's retrospective asked for and the one this whole
ticket exists to make possible."""
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


def test_klc128_integrate_ack_after_real_ff_merge_reports_real_drift_and_retrieval(
    tmp_path, monkeypatch
):
    """AC-11: the drift report's `scope_drift.skipped` is `None` (a real
    result, not 'no changed files detected') and the retrieval record's
    `ground_truth_files` count equals the ticket branch's real changed-file
    count, after a real fast-forward merge and push."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-928"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
        ("widgets/other.py", "b = 1\n", f"{ticket} step-2: add b"),
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
    assert report["scope_drift"]["skipped"] is None, \
        "KLC-110's retro regression: this must be a REAL result, not skipped"

    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    rec = _retrieval_rec(tdir.parents[2], tdir.name)
    assert rec["status"] == "ok"
    assert rec["ground_truth_files"] == 2
