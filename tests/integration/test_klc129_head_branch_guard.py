"""KLC-129 step-1/step-3 — the integrate ground-truth resolver
(`_resolve_ground_truth`) and the pre-merge-range recorder
(`_pre_merge_range_patch`) refuse to trust or persist a live `HEAD` diff that
visibly belongs to a DIFFERENT ticket's branch (AC-1, AC-2). See raw.md
F-001: the incident this ticket fixes was a checkout sitting on
`feature/klc-114-step-ledger` while another ticket's ack ran.

step-3 (review round 1): the e2e fixtures below now use the REAL,
lowercase `feature/klc-<n>-<slug>` branch shape (external review MEDIUM #1
— the all-uppercase `feature/KLC-9xx` shape every branch used before this
step is not what any real branch in this project looks like; a scratch
mutation test that dropped `re.IGNORECASE` left all of them green). A
parametrized, stubbed-`_git` unit test of `_head_branch_mismatch` itself
(no fixture repo needed) pins the detector's edge cases directly: lowercase
own/foreign branches, KLC-12-vs-KLC-129 numeric-prefix confusion in both
directions, detached HEAD, a keyless branch, a branch naming several keys,
a branch naming the ticket's OWN key plus another (external review MEDIUM
#3 — must resolve to "own branch", not a mismatch), and a non-KLC project
key (external review MEDIUM #2 — the key pattern is now built from the
ACKED ticket's own prefix, not a hardcoded `KLC-`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _ground_truth,
    _read_meta,
    _run_ack,
    _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def test_ground_truth_falls_back_to_recorded_range_when_head_is_another_tickets_branch(
    tmp_path, monkeypatch
):
    """AC-1 negative: KLC-940 has a recorded `pre_merge_range` from its own,
    earlier build ack. HEAD is then moved to a DIFFERENT ticket's branch
    (the REAL lowercase `feature/klc-941-add-a-gizmo` shape, step-3) with its
    own, different diff. Resolving KLC-940's ground truth must NOT trust
    that live diff (it belongs to KLC-941) — it must fall back to KLC-940's
    own recorded range instead, so `source` is never `"live-merge-base"`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-940"
    _branch_with_commits(clone, ticket_a, [
        ("widgets/thing.py", "a = 1\n", f"{ticket_a} step-1: add a"),
    ], branch="feature/klc-940-add-a-widget")
    _seed_ticket(clone, ticket_a, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket_a, "build", monkeypatch=monkeypatch, pick=1) == 0
    recorded_range = _read_meta(clone, ticket_a)["pre_merge_range"]
    assert recorded_range["base"] and recorded_range["head"], (
        "the build ack must have recorded a real range")

    ticket_b = "KLC-941"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-941-add-a-gizmo")

    gt = _ground_truth(clone, ticket_a, monkeypatch=monkeypatch)
    assert gt["source"] == "recorded-range"
    assert gt["paths"] == {"widgets/thing.py"}
    assert gt["reason"] is None


def test_ground_truth_resolves_to_none_with_reason_when_no_recorded_range_and_head_is_wrong_branch(
    tmp_path, monkeypatch
):
    """AC-1 fail-closed twin: KLC-942 has NO recorded range at all (never
    acked build). HEAD sits on a different ticket's branch (the real
    lowercase `feature/klc-943-add-a-gizmo` shape, step-3). The resolver
    must reject the live diff (it's KLC-943's, not KLC-942's) and, with no
    recorded range to fall back to, resolve to `source="none"` with a
    reason that names the mismatch — never silently trusting the wrong
    diff."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-942"
    _seed_ticket(clone, ticket_a, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    ticket_b = "KLC-943"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-943-add-a-gizmo")

    gt = _ground_truth(clone, ticket_a, monkeypatch=monkeypatch)
    assert gt["source"] == "none"
    assert gt["paths"] == set()
    assert gt["reason"] is not None
    assert "KLC-943" in gt["reason"]


def test_ground_truth_still_uses_live_diff_on_the_tickets_own_branch(tmp_path, monkeypatch):
    """Regression: HEAD on the ticket's OWN branch (the real lowercase
    `feature/klc-944-add-a-widget` shape, step-3) resolves exactly as
    today — the branch-mismatch guard must never fire on a false
    positive."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-944"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch="feature/klc-944-add-a-widget")
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "live-merge-base"
    assert gt["paths"] == {"widgets/thing.py"}


def test_pre_merge_range_patch_skips_recording_when_head_is_another_tickets_branch(
    tmp_path, monkeypatch
):
    """AC-2 negative: a build ack for KLC-945 runs while HEAD sits on a
    DIFFERENT ticket's branch (the real lowercase `feature/klc-946-add-a-
    gizmo` shape, step-3). The recorder must stage NO `pre_merge_range` for
    KLC-945 — persisting the other ticket's diff as KLC-945's ground truth
    would outlive this mis-timed ack (F-004)."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-945"
    _seed_ticket(clone, ticket_a, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    ticket_b = "KLC-946"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-946-add-a-gizmo")

    assert _run_ack(clone, ticket_a, "build", monkeypatch=monkeypatch, pick=1) == 0
    meta = _read_meta(clone, ticket_a)
    assert "pre_merge_range" not in meta


def test_pre_merge_range_patch_records_normally_on_the_tickets_own_branch(tmp_path, monkeypatch):
    """Regression: a build ack run on the ticket's OWN branch (the real
    lowercase `feature/klc-947-add-a-widget` shape, step-3) still records
    its pre-merge range exactly as before (KLC-128 behaviour unaffected)."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-947"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch="feature/klc-947-add-a-widget")
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    meta = _read_meta(clone, ticket)
    assert "pre_merge_range" in meta
    assert meta["pre_merge_range"]["base"]
    assert meta["pre_merge_range"]["head"]


# ---------------------------------------------------------------------------
# step-3 (review round 1) — a stubbed-`_git` unit test of the detector itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("branch,ticket,expect_mismatch,note", [
    ("feature/klc-129-foreign-branch-guard", "KLC-129", False,
     "lowercase own branch, with a slug"),
    ("feature/klc-114-step-ledger", "KLC-129", True,
     "lowercase foreign branch — the actual F-001 incident shape"),
    ("feature/klc-129-x", "KLC-12", True,
     "prefix confusion: KLC-12 acked while HEAD names KLC-129"),
    ("feature/klc-12-x", "KLC-129", True,
     "prefix confusion, reversed: KLC-129 acked while HEAD names KLC-12"),
    ("HEAD", "KLC-129", False, "detached HEAD — rev-parse literally returns 'HEAD'"),
    ("main", "KLC-129", False, "no ticket key embedded at all"),
    ("klc-state", "KLC-129", False, "a project-name-shaped branch with no digits"),
    ("", "KLC-129", False, "empty branch string (git failure degrade)"),
    ("feature/klc-129-followup-klc-128", "KLC-129", False,
     "own key AND another key present -> still the ticket's own branch"),
    ("feature/klc-114-and-klc-115", "KLC-129", True,
     "several foreign keys, none of them the acked ticket's own"),
    ("feature/jat-13-thing", "JAT-12", True,
     "a non-KLC project key: dynamic prefix must still catch a foreign JAT branch"),
    ("feature/jat-12-thing", "JAT-12", False,
     "a non-KLC project key: dynamic prefix must recognise its OWN branch"),
])
def test_head_branch_mismatch_unit_cases(monkeypatch, branch, ticket, expect_mismatch, note):
    """AC-1/AC-2 (step-3, code review LOW #2 + external review MEDIUM #1/#2/#3):
    a pure unit test of `_head_branch_mismatch` — `_git` is stubbed so no
    fixture repo is needed, isolating the detector's own branch-name logic
    from the ack/recording machinery the other tests in this file already
    exercise end to end."""
    import phase_completion as _pc
    monkeypatch.setattr(_pc, "_git", lambda args, repo=None: branch)

    result = _pc._head_branch_mismatch(ticket)
    assert (result is not None) == expect_mismatch, note
