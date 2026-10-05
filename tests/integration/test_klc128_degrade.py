"""KLC-128 step-3 — AC-8: the integrate ack degrades the drift scope section
and the retrieval record with a NAMED reason (never a bare generic skip, and
never a key-grep fallback) when the live diff is empty and no usable range
is recorded."""
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
    _merged_no_recording,
    _read_meta,
    _retrieval_rec,
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


def test_legacy_ticket_with_no_recorded_range_degrades_with_a_named_reason(tmp_path, monkeypatch):
    """AC-8, case 1/2 (legacy ticket, no migration per the spec's rollout
    assumption): a merged ticket whose meta.json predates this fix (no
    `pre_merge_range` key at all) and an empty live diff — both the drift
    scope section and the retrieval record degrade, each carrying a reason
    naming 'no recorded pre-merge range'."""
    ticket = "KLC-922"
    clone = _merged_no_recording(tmp_path, ticket)

    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")
    assert "pre_merge_range" not in _read_meta(clone, ticket)

    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    report = _last_drift_report()
    assert "no recorded pre-merge range" in (report["scope_drift"]["skipped"] or "")

    rec = _retrieval_rec(tdir.parents[2], tdir.name)
    assert rec["status"] == "unavailable"
    assert "no recorded pre-merge range" in rec["reason"]


def test_range_pointing_at_objects_absent_from_this_clone_degrades_with_a_named_reason(
    tmp_path, monkeypatch
):
    """AC-8, case 2/2: a recorded range whose shas are real (they exist in
    the clone that recorded them) but are ABSENT from THIS clone — built via
    a squash merge (whose synthetic squash commit never carries the original
    per-commit objects as ancestors, so `git push` never sends them) plus a
    SECOND, independently-cloned checkout that only ever fetched `origin`
    (never the ticket branch) — mirrors F-011's squash-then-branch-deletion
    scenario. Degrades with a reason naming the unresolved sha, never a
    silent empty result."""
    _bare_and_clone(tmp_path)
    clone_a = tmp_path / "clone"
    ticket = "KLC-923"
    _branch_with_commits(clone_a, ticket, [
        ("widgets/thing.py", "a = 1\n", "add a"),
    ])
    _seed_ticket(clone_a, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone_a, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    recorded_range = _read_meta(clone_a, ticket)["pre_merge_range"]

    _merge(clone_a, ticket, "squash")   # the squash commit carries no reference
                                       # to the original per-commit objects

    # A second, fresh clone of origin — it never fetched the (deleted, local-only)
    # feature branch, so those per-commit objects were never transferred.
    from _klc128_fixtures import _git
    clone_b = tmp_path / "clone_b"
    _git(tmp_path, "clone", str(tmp_path / "origin.git"), str(clone_b))
    _git(clone_b, "config", "user.email", "alice@example.com")
    _git(clone_b, "config", "user.name", "Alice")
    _git(clone_b, "config", "commit.gpgsign", "false")

    tdir = _seed_ticket(clone_b, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range=recorded_range)
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")

    assert _run_ack(clone_b, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    report = _last_drift_report()
    reason = report["scope_drift"]["skipped"] or ""
    # KLC-128 step-7 (review MEDIUM, D-128-3): the new ancestry pre-check
    # (`git merge-base <base> <head>`) fails identically for "objects absent
    # from this clone" and "unrelated history" — git cannot resolve either
    # sha, so the SAME degrade reason fires for both, one call earlier than
    # the old "not resolvable in this clone" diff-based check.
    assert "recorded pre-merge range base is not an ancestor of head" in reason
    assert recorded_range["base"] in reason or recorded_range["head"] in reason


def test_squash_with_keyless_subject_never_falls_back_to_key_grep(tmp_path, monkeypatch):
    """NEGATIVE twin (the ticket's own hard 'never falls back to the
    key-grep derivation' clause): a squash merge with a keyless subject and a
    corrupted/absent recorded range — the degrade path is taken (AC-8's
    `none`/`unavailable` shape) and, via the git-invocation log, no `log`
    verb and no `--grep` argument ever appears."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-924"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", "add a"),
        ("widgets/thing.py", "a = 2\n", "review-fix: tweak a"),
    ])
    # No recording ack — the recorded range is absent.
    _merge(clone, ticket, "squash")

    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    (tdir / "retrieval_trace.json").write_text(json.dumps(_OK_TRACE), encoding="utf-8")

    log = _count_git(monkeypatch)
    assert _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1) == 0

    assert not any(call and call[0] == "log" for call in log), log
    assert not any("--grep" in call for call in log), log

    report = _last_drift_report()
    assert report["ground_truth_source"] == "none"
    assert _retrieval_rec(tdir.parents[2], tdir.name)["status"] == "unavailable"
