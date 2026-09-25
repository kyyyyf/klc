"""tests/integration/test_klc110_ack_cost_bound.py — KLC-110 step-5: AC-21's
cost bound, and the D-300/D-301 track-scale gate that closes the
revision-1 review's F-1 finding (a track whose drift arm skips must also
skip the retrieval producer's diff resolution, REGARDLESS of trace status)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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


def _fake_load_modules(calls):
    """KLC-110 review round 2, step-13 (LOW, AC-21): a call-counting wrapper
    for `phase_completion._load_modules`, mirroring `_fake_git` above — the
    module map is the OTHER index artifact AC-21 explicitly sanctions
    reading, so its own read count needs the same asserted bound the git
    call count already has."""
    def _load():
        calls.append("load_modules")
        return {"modules": []}
    return _load


def _write_ticket(tmp_path, key, track, trace=None):
    d = tmp_path / ".klc" / "tickets" / key
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"phase": "integrate:work", "track": track}), encoding="utf-8")
    if trace is not None:
        (d / "retrieval_trace.json").write_text(json.dumps(trace), encoding="utf-8")
    return d


_OK_TRACE = {"status": "ok", "confidence": "high", "files_likely_to_edit": ["a.py"],
             "files_to_read_first": [], "tests_to_read_or_run": [],
             "affected_modules_hint": []}


def test_evaluator_adds_no_extra_git_call_and_reads_only_trace_and_module_map(
    tmp_path, monkeypatch
):
    """AC-21: no git invocation beyond the one the ack already issues — a
    pre-warmed shared cache (as the ack's drift producer would have left
    behind) means the retrieval producer issues ZERO further git calls."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_ticket(tmp_path, "KLC-E", "M", _OK_TRACE)

    calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(calls))
    monkeypatch.setattr(_pc, "_load_modules", lambda: {"modules": []})

    cache = {"committed": ({"m"}, {"a.py"})}  # the ack already resolved this
    _pc._retrieval_advisories("KLC-E", False, committed=cache)

    assert calls == [], calls


def test_xs_ticket_without_usable_trace_adds_zero_git_invocations(tmp_path, monkeypatch):
    """The degrade gate (D-214): an XS ticket with no usable trace adds
    zero git invocations."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_ticket(tmp_path, "KLC-X1", "XS")  # no retrieval_trace.json at all

    calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(calls))

    recs = _pc._retrieval_advisories("KLC-X1", False)
    assert calls == [], calls
    assert recs == []


def test_xs_ticket_with_status_ok_trace_adds_zero_git_invocations(tmp_path, monkeypatch):
    """The track gate (D-300): an XS ticket whose trace resolves to
    status:"ok" — a SYNTHETIC fixture no real trace on this repo provides
    today — still adds zero git invocations, because the track gate runs
    BEFORE the degrade checks and before any diff resolution. This is the
    regression the revision-1/revision-2 review found: a producer gated
    only on trace status reopens AC-21's cost bound the moment a small
    ticket's trace is ok."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_ticket(tmp_path, "KLC-X2", "XS", _OK_TRACE)

    calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(calls))
    monkeypatch.setattr(_pc, "_load_modules", lambda: {"modules": []})

    recs = _pc._retrieval_advisories("KLC-X2", False)
    assert calls == [], calls
    assert recs == []


def test_m_ticket_resolves_the_committed_diff_exactly_once_across_both_producers(
    tmp_path, monkeypatch
):
    """The gate scales the cost, it does not disable the feature: an M
    ticket runs both producers and the monkeypatched runner sees one
    merge-base and one diff in total, via the shared per-ack cache
    (D-216/D-301)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_ticket(tmp_path, "KLC-M1", "M", _OK_TRACE)

    calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(calls))
    monkeypatch.setattr(_pc, "_load_modules", lambda: {"modules": []})
    monkeypatch.setattr(
        _pc, "_drift",
        type("FakeDrift", (), {
            "write_report": staticmethod(
                lambda ticket: {"scope_drift": {}, "step_without_commit": {}}),
            "compare": staticmethod(
                lambda ticket: {"scope_drift": {}, "step_without_commit": {}}),
        }))

    cache: dict = {}
    _pc._drift_advisories("KLC-M1", False, committed=cache)
    _pc._retrieval_advisories("KLC-M1", False, committed=cache)

    merge_base_calls = [c for c in calls if c[0] == "merge-base"]
    diff_calls = [c for c in calls if c[0] == "diff"]
    assert len(merge_base_calls) == 1, calls
    assert len(diff_calls) == 1, calls


def test_m_ticket_reads_the_module_map_exactly_once_across_both_producers(
    tmp_path, monkeypatch
):
    """AC-21 (KLC-110 review round 2, step-13): the module map is the OTHER
    index artifact AC-21 sanctions reading — an M ticket running both
    producers must read `modules.json` exactly ONCE in total, via the SAME
    shared per-ack cache `_committed_cached`/`_modules_data_cached` reuse
    (D-216/D-110-11's cache-sharing extended to the module map)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_ticket(tmp_path, "KLC-M2", "M", _OK_TRACE)

    git_calls: list = []
    modules_calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(git_calls))
    monkeypatch.setattr(_pc, "_load_modules", _fake_load_modules(modules_calls))
    monkeypatch.setattr(
        _pc, "_drift",
        type("FakeDrift", (), {
            "write_report": staticmethod(
                lambda ticket: {"scope_drift": {}, "step_without_commit": {}}),
            "compare": staticmethod(
                lambda ticket: {"scope_drift": {}, "step_without_commit": {}}),
        }))

    cache: dict = {}
    _pc._drift_advisories("KLC-M2", False, committed=cache)
    _pc._retrieval_advisories("KLC-M2", False, committed=cache)

    assert len(modules_calls) == 1, modules_calls


def test_two_tickets_in_one_process_do_not_share_a_cached_diff(tmp_path, monkeypatch):
    """The cache-is-a-parameter regression (D-216): two tickets scored in
    the same process, each with its OWN fresh cache dict, each resolve
    their own committed diff — a module-level global would have wrongly
    shared one ticket's diff with the other."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_ticket(tmp_path, "KLC-T1", "M", _OK_TRACE)
    _write_ticket(tmp_path, "KLC-T2", "M", _OK_TRACE)

    calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(calls))
    monkeypatch.setattr(_pc, "_load_modules", lambda: {"modules": []})

    _pc._retrieval_advisories("KLC-T1", False, committed={})
    _pc._retrieval_advisories("KLC-T2", False, committed={})

    merge_base_calls = [c for c in calls if c[0] == "merge-base"]
    assert len(merge_base_calls) == 2, calls
