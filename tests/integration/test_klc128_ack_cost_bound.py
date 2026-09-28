"""KLC-128 step-5 — AC-10: one complete `klc ack` integrate run, including
the WORK→ack-needed recursion in `ack.py`, computes the ground truth ONCE and
shares it across the drift check, the retrieval evaluator and the
`ack.py` integrate scope guard."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _count_git,
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


def _count_scope_delta_git(monkeypatch):
    import scope_delta as _sd
    calls: list = []
    real = _sd._git_changed_files

    def _wrapped(root):
        calls.append(1)
        return real(root)

    monkeypatch.setattr(_sd, "_git_changed_files", _wrapped)
    return calls


def _merged_ticket_with_range(tmp_path, ticket, *, track, monkeypatch, risk_tags=None):
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track=track,
                affected_modules=["widgets"], modules=_MODULES, risk_tags=risk_tags)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    _merge(clone, ticket, "ff-only")
    tdir = clone / ".klc" / "tickets" / ticket
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")
    _set_phase(clone, ticket, "integrate:work")
    return clone, tdir


def test_klc128_integrate_ack_computes_ground_truth_once_across_recursion(tmp_path, monkeypatch):
    """AC-10 (the spec's own clause): drives one full `ack.run` end to end
    for a merged M ticket with a recorded range, entering at `integrate:work`
    so the real WORK→ack-needed recursion fires. The total ground-truth
    git-call count across the ENTIRE run is at most one `merge-base` (live),
    one live `diff`, one `merge-base` (KLC-128 step-7 D-128-3: the ancestry
    pre-check on the recorded-range leg — an EXPLICIT, named, review-required
    extra call, updating the bound from <= 3 to <= 4) and one recorded-range
    `diff` (<= 4 total), never one bound PER producer — and the guard's own
    pre-existing `scope_delta` diff (D-211, out of this bound) issues zero
    calls too, since the guard shares the already-resolved ground truth
    instead of falling back to it."""
    ticket = "KLC-934"
    clone, tdir = _merged_ticket_with_range(tmp_path, ticket, track="M", monkeypatch=monkeypatch)

    git_log = _count_git(monkeypatch)
    sd_calls = _count_scope_delta_git(monkeypatch)

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    merge_base_calls = [c for c in git_log if c[0] == "merge-base"]
    diff_calls = [c for c in git_log if c[0] == "diff"]
    assert len(merge_base_calls) <= 2, git_log
    assert len(diff_calls) <= 2, git_log
    assert len(git_log) <= 4, git_log
    assert sd_calls == [], "the guard must share the resolved ground truth, not re-derive it"


@pytest.mark.parametrize("track,risk_tags", [("XS", None), ("S", None)])
def test_xs_ticket_and_escalation_free_s_ticket_issue_zero_ground_truth_git_calls(
    tmp_path, monkeypatch, track, risk_tags
):
    """AC-10 negative/track-gate companion: an XS ticket, and separately an S
    ticket with no escalation signal, issue ZERO ground-truth-related git
    invocations across the whole run — preserving KLC-110 AC-21/C-001's
    existing track gate under the now-shared cache. (regression pin: the
    guard's own pre-KLC-128 `scope_delta` diff is out of this bound, D-211.)"""
    ticket = f"KLC-935{track}"
    clone, tdir = _merged_ticket_with_range(tmp_path, ticket, track=track,
                                            monkeypatch=monkeypatch, risk_tags=risk_tags)

    git_log = _count_git(monkeypatch)

    import phase_completion as _pc
    seen: list = []
    real_igt = _pc.integrate_ground_truth

    def _wrapped_igt(t, *, cache=None):
        seen.append(t)
        return real_igt(t, cache=cache)

    monkeypatch.setattr(_pc, "integrate_ground_truth", _wrapped_igt)

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    assert git_log == [], git_log
    assert seen == [], "integrate_ground_truth must never be invoked on a track-skipped ticket"


def test_scope_guard_resolves_the_same_file_set_as_drift_and_retrieval(tmp_path, monkeypatch):
    """test-plan-review F-1: in the same full `ack.run` over a merged M
    ticket, the file set the `ack.py` integrate scope guard evaluates is
    content-identical to the set the drift check and the retrieval evaluator
    scored — the call-count bound alone cannot be met by a guard silently
    using a divergent set."""
    import ack as _ack_mod
    import drift_check as _dc
    import retrieval_eval as _reval

    ticket = "KLC-936"
    clone, tdir = _merged_ticket_with_range(tmp_path, ticket, track="M", monkeypatch=monkeypatch)

    seen: dict = {}

    real_scope_compare = _ack_mod._sd.compare

    def _wrapped_sd_compare(t, *, changed_files=None):
        seen["guard_changed_files"] = changed_files
        return real_scope_compare(t, changed_files=changed_files)

    monkeypatch.setattr(_ack_mod._sd, "compare", _wrapped_sd_compare)

    real_write_report = _dc.write_report

    def _wrapped_write_report(t, *, repo=None, ground_truth=None):
        seen["drift_ground_truth_paths"] = set((ground_truth or {}).get("paths") or ())
        return real_write_report(t, repo=repo, ground_truth=ground_truth)

    monkeypatch.setattr(_dc, "write_report", _wrapped_write_report)

    real_consume = _reval.consume

    def _wrapped_consume(t, trace, committed_modules, committed_paths, track, *, persist,
                         modules_data=None, ground_truth=None):
        seen["reval_committed_paths"] = set(committed_paths)
        return real_consume(t, trace, committed_modules, committed_paths, track,
                           persist=persist, modules_data=modules_data, ground_truth=ground_truth)

    monkeypatch.setattr(_reval, "consume", _wrapped_consume)

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    assert seen["guard_changed_files"] is not None
    assert set(seen["guard_changed_files"]) == seen["drift_ground_truth_paths"]
    assert set(seen["guard_changed_files"]) == seen["reval_committed_paths"]


def test_s_ticket_with_escalation_signal_computes_ground_truth_once(tmp_path, monkeypatch):
    """An S ticket WITH an escalation signal (a coordination risk tag) runs
    the evaluators and computes the ground truth exactly once across the
    recursion — same bound as the M case (<= 4, KLC-128 step-7 D-128-3)."""
    ticket = "KLC-937"
    clone, tdir = _merged_ticket_with_range(
        tmp_path, ticket, track="S", monkeypatch=monkeypatch, risk_tags=["coordination"])

    git_log = _count_git(monkeypatch)
    sd_calls = _count_scope_delta_git(monkeypatch)

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    merge_base_calls = [c for c in git_log if c[0] == "merge-base"]
    diff_calls = [c for c in git_log if c[0] == "diff"]
    assert len(merge_base_calls) <= 2, git_log
    assert len(diff_calls) <= 2, git_log
    assert len(git_log) <= 4, git_log
    assert sd_calls == []


def test_ground_truth_scope_is_cleared_after_each_ack_run(tmp_path, monkeypatch):
    """Two tickets acked in sequence in ONE process each resolve their OWN
    ground truth, and the run-scope is closed after each `ack.run` — a
    module-level global (rather than a scope opened/closed per run) would
    wrongly leak one ticket's resolved set into the next."""
    import phase_completion as _pc

    ticket_a = "KLC-938"
    clone_a, _ = _merged_ticket_with_range(tmp_path, ticket_a, track="M", monkeypatch=monkeypatch)
    assert _pc._RUN_SCOPE is None
    assert _run_ack(clone_a, ticket_a, "integrate", monkeypatch=monkeypatch, pick=1) == 0
    assert _pc._RUN_SCOPE is None, "the scope must be cleared after the outermost ack.run returns"

    tmp_path_b = tmp_path / "b"
    tmp_path_b.mkdir()
    ticket_b = "KLC-939"
    clone_b, _ = _merged_ticket_with_range(tmp_path_b, ticket_b, track="M", monkeypatch=monkeypatch)
    assert _run_ack(clone_b, ticket_b, "integrate", monkeypatch=monkeypatch, pick=1) == 0
    assert _pc._RUN_SCOPE is None
