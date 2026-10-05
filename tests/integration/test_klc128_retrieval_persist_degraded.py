"""KLC-128 step-4 — AC-9: `_retrieval_advisories` persists an `unavailable`
record to the derived retrieval row (meta.json no longer carries it, KLC-176) and one line to
`.klc/knowledge/retrieval-eval.jsonl` when the trace is absent or its status
is not `ok`, on the persisting path, with ZERO git invocations and no
module-map read (KLC-110's spec intended this; it was a bug, not an intended
behaviour, per design/options.md's degraded-trace persistence gap)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _count_git,
    _merge,
    _read_meta,
    _retrieval_rec,
    _run_ack,
    _seed_ticket,
    _set_phase,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def _merged_ticket(tmp_path, ticket, *, monkeypatch):
    """A real, merged fixture ticket (per the harness note, every KLC-128
    test drives one) — even though this producer's degrade branch itself
    never calls git."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    _merge(clone, ticket, "ff-only")
    tdir = clone / ".klc" / "tickets" / ticket
    return clone, tdir


def _flush_staged_patch(ticket: str) -> None:
    """`_retrieval_advisories`'s persisting path only STAGES the meta patch
    (`lifecycle.stage_meta_patch`, the same seam `ack.py`'s own
    manual-completion branch rides its `state_tx` with) — it is applied to
    disk only on the next `lifecycle.set_state`. A test calling the producer
    directly (bypassing `ack.run`) must flush it the same way `ack.py` does."""
    import lifecycle as _lc
    _lc.set_state(ticket, "integrate", "ack-needed", event="manual-completion", note="test")


def _count_modules(monkeypatch):
    import phase_completion as _pc
    calls: list = []
    real = _pc._load_modules

    def _wrapped():
        calls.append(1)
        return real()

    monkeypatch.setattr(_pc, "_load_modules", _wrapped)
    return calls


def test_absent_trace_persists_unavailable_record_with_zero_git_and_no_module_map(
    tmp_path, monkeypatch
):
    """AC-9 positive: no `retrieval_trace.json` at all on a merged ticket —
    persists `meta.json:metrics.retrieval.status == "unavailable"`, one new
    line in `retrieval-eval.jsonl`, and zero EXTRA git/module-map reads for
    this producer.

    KLC-128 step-8 (review MEDIUM): the degraded branch now actively
    resolves `integrate_ground_truth(ticket, cache=committed)` instead of
    passively reading a maybe-absent `committed['ground_truth']`, so the
    persisted record's `ground_truth_source` is reliable regardless of
    producer-call ordering. That resolution is zero-cost ONLY once the
    SAME cache already has it — exactly what `_drift_advisories` (which
    runs first in the real `_can_complete_generic` ordering) leaves behind
    — so this test reproduces that ordering explicitly, BEFORE the git/
    module-map counters start, and asserts the retrieval producer itself
    adds nothing further."""
    ticket = "KLC-929"
    clone, tdir = _merged_ticket(tmp_path, ticket, monkeypatch=monkeypatch)
    _set_phase(clone, ticket, "integrate:work")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc

    cache: dict = {}
    _pc._drift_advisories(ticket, True, committed=cache)  # resolves+caches, as the real ack does

    git_log = _count_git(monkeypatch)
    mod_calls = _count_modules(monkeypatch)

    _pc._retrieval_advisories(ticket, True, committed=cache)
    _flush_staged_patch(ticket)

    assert git_log == [], git_log
    assert mod_calls == [], mod_calls
    rec = _retrieval_rec(clone, ticket)
    assert rec["status"] == "unavailable"
    assert "no retrieval trace" in rec["reason"]
    assert rec["ground_truth_source"] == "recorded-range"

    lines = (clone / ".klc" / "knowledge" / "retrieval-eval.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["ticket"] == ticket


def test_non_ok_status_trace_also_persists_unavailable(tmp_path, monkeypatch):
    """AC-9, companion: a `retrieval_trace.json` present but `status` not
    `"ok"` — same persistence + zero-EXTRA-cost assertions, proving the fix
    is 'absent OR non-ok', not 'absent only'. See the sibling test above for
    why the cache is pre-warmed via `_drift_advisories` first (KLC-128
    step-8)."""
    ticket = "KLC-930"
    clone, tdir = _merged_ticket(tmp_path, ticket, monkeypatch=monkeypatch)
    _set_phase(clone, ticket, "integrate:work")
    (tdir / "retrieval_trace.json").write_text(
        json.dumps({"status": "degraded"}), encoding="utf-8")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc

    cache: dict = {}
    _pc._drift_advisories(ticket, True, committed=cache)

    git_log = _count_git(monkeypatch)
    mod_calls = _count_modules(monkeypatch)

    _pc._retrieval_advisories(ticket, True, committed=cache)
    _flush_staged_patch(ticket)

    assert git_log == [], git_log
    assert mod_calls == [], mod_calls
    rec = _retrieval_rec(clone, ticket)
    assert rec["status"] == "unavailable"
    assert "status is" in rec["reason"]
    assert rec["ground_truth_source"] == "recorded-range"


def test_absent_and_non_ok_degraded_records_carry_distinct_reasons(tmp_path, monkeypatch):
    """test-plan-review F-2: the persisted `unavailable` record for an
    ABSENT trace and for a present trace with a non-`ok` status carry
    DIFFERENT reason strings, each naming its own cause — asserted on the
    persisted meta record, not only on the status."""
    import phase_completion as _pc

    ticket_a = "KLC-931"
    clone_a, _ = _merged_ticket(tmp_path, ticket_a, monkeypatch=monkeypatch)
    _set_phase(clone_a, ticket_a, "integrate:work")
    monkeypatch.setenv("PROJECT_ROOT", str(clone_a))
    _pc._retrieval_advisories(ticket_a, True, committed={})
    _flush_staged_patch(ticket_a)
    reason_absent = _retrieval_rec(clone_a, ticket_a)["reason"]

    tmp_path_b = tmp_path / "b"
    tmp_path_b.mkdir()
    ticket_b = "KLC-932"
    clone_b, tdir_b = _merged_ticket(tmp_path_b, ticket_b, monkeypatch=monkeypatch)
    _set_phase(clone_b, ticket_b, "integrate:work")
    (tdir_b / "retrieval_trace.json").write_text(
        json.dumps({"status": "degraded"}), encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(clone_b))
    _pc._retrieval_advisories(ticket_b, True, committed={})
    _flush_staged_patch(ticket_b)
    reason_non_ok = _retrieval_rec(clone_b, ticket_b)["reason"]

    assert reason_absent != reason_non_ok
    assert "no retrieval trace" in reason_absent
    assert "status is" in reason_non_ok


def test_degraded_branch_resolves_ground_truth_itself_even_when_drift_never_ran_first(
    tmp_path, monkeypatch
):
    """KLC-128 step-8 (review MEDIUM, the actual behaviour change): calling
    `_retrieval_advisories` in isolation — WITHOUT `_drift_advisories` having
    run first in the SAME cache (the old code's implicit, undocumented
    dependency) — must still persist a reliable `ground_truth_source`. The
    old passive `committed.get('ground_truth')` would silently return
    `None` here and OMIT the field entirely; the fix actively resolves it
    via `integrate_ground_truth`."""
    ticket = "KLC-955"
    clone, tdir = _merged_ticket(tmp_path, ticket, monkeypatch=monkeypatch)
    _set_phase(clone, ticket, "integrate:work")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc

    _pc._retrieval_advisories(ticket, True, committed={})   # NOTHING pre-resolved this cache
    _flush_staged_patch(ticket)

    rec = _retrieval_rec(clone, ticket)
    assert rec["status"] == "unavailable"
    assert rec.get("ground_truth_source") == "recorded-range"


def test_skipped_track_degraded_branch_still_issues_zero_git_calls(tmp_path, monkeypatch):
    """KLC-128 step-8 (review MEDIUM): the AC-9 zero-git bound still holds on
    a track-skipped ticket (XS) — `integrate_evaluators_run`'s gate runs
    BEFORE the degraded branch's new `integrate_ground_truth` call, so an XS
    ticket with an absent trace never reaches it at all."""
    ticket = "KLC-954"
    clone, tdir = _merged_ticket(tmp_path, ticket, monkeypatch=monkeypatch)
    meta = _read_meta(clone, ticket)
    meta["track"] = "XS"
    (clone / ".klc" / "tickets" / ticket / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    _set_phase(clone, ticket, "integrate:work")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc
    git_log = _count_git(monkeypatch)
    mod_calls = _count_modules(monkeypatch)

    recs = _pc._retrieval_advisories(ticket, True, committed={})

    assert git_log == [], git_log
    assert mod_calls == [], mod_calls
    assert recs == []


def test_end_to_end_absent_trace_retrieval_record_carries_recorded_range_source(
    tmp_path, monkeypatch
):
    """KLC-128 step-8(b) (review MEDIUM): a full `ack.run` on a merged
    ticket with a recorded range and an ABSENT trace — the persisted
    degraded retrieval record still carries the correct
    `ground_truth_source`, proving the degraded branch no longer depends on
    the drift producer having already resolved the shared cache (it now
    resolves via `integrate_ground_truth` itself, at zero EXTRA cost once
    drift's own resolution is cached — the real `_sources` ordering runs
    drift first)."""
    ticket = "KLC-952"
    clone, tdir = _merged_ticket(tmp_path, ticket, monkeypatch=monkeypatch)
    _set_phase(clone, ticket, "integrate:work")   # no retrieval_trace.json at all

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    rec = _retrieval_rec(clone, ticket)
    assert rec["status"] == "unavailable"
    assert rec["ground_truth_source"] == "recorded-range"


def test_end_to_end_absent_trace_retrieval_record_carries_none_source_when_nothing_is_usable(
    tmp_path, monkeypatch
):
    """KLC-128 step-8(b), `none` twin: a merged ticket with NO recorded
    range and an ABSENT trace — the persisted degraded retrieval record
    carries `ground_truth_source: "none"`."""
    from _klc128_fixtures import _merged_no_recording

    ticket = "KLC-953"
    clone = _merged_no_recording(tmp_path, ticket)
    _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    # no retrieval_trace.json

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    rec = _retrieval_rec(clone, ticket)
    assert rec["status"] == "unavailable"
    assert rec["ground_truth_source"] == "none"


def test_probe_persist_false_still_persists_nothing_for_the_degraded_branch(tmp_path, monkeypatch):
    """NEGATIVE/fail-closed twin (regression pin): the same absent-trace
    fixture, probed with `persist=False` — neither `meta.json` nor
    `retrieval-eval.jsonl` changes (C-004, KLC-110 AC-10/KLC-062)."""
    ticket = "KLC-933"
    clone, tdir = _merged_ticket(tmp_path, ticket, monkeypatch=monkeypatch)
    _set_phase(clone, ticket, "integrate:work")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc
    meta_path = clone / ".klc" / "tickets" / ticket / "meta.json"
    before = meta_path.read_bytes()

    _pc._retrieval_advisories(ticket, False, committed={})

    assert meta_path.read_bytes() == before
    assert not (clone / ".klc" / "knowledge" / "retrieval-eval.jsonl").exists()
