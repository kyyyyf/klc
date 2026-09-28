"""KLC-128 step-1 — record the pre-merge range at the build, review and
manual acks (AC-4).

Every test drives a REAL git fixture (a bare ``origin.git`` plus a working
clone) and the real ``ack.run`` entry point — never a stubbed ``_git`` or a
canned ``compare()`` return (test-plan harness note, KLC-110 retro F-016).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _add_commit,
    _bare_and_clone,
    _branch_with_commits,
    _git,
    _read_meta,
    _rev_parse,
    _run_ack,
    _seed_ticket,
    _set_phase,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MODULES = [{"name": "widgets", "path": "widgets/"}]


def test_build_ack_stages_pre_merge_range_when_live_diff_non_empty(tmp_path, monkeypatch):
    """AC-4: a persisting build ack on a track whose integrate evaluators run
    (track M) stages `pre_merge_range {base, head, recorded_at_phase,
    recorded_at}` into meta.json when its live diff minus `.klc/` is
    non-empty — with real 40-hex commit shas from the real fixture repo."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-901"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    expected_base = _rev_parse(clone, "main")
    expected_head = _rev_parse(clone, "HEAD")
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    rc = _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1)
    assert rc == 0

    meta = _read_meta(clone, ticket)
    rng = meta.get("pre_merge_range")
    assert rng is not None, "expected pre_merge_range to be staged"
    assert _SHA_RE.match(rng["base"] or ""), rng
    assert _SHA_RE.match(rng["head"] or ""), rng
    assert rng["base"] == expected_base
    assert rng["head"] == expected_head
    assert rng["recorded_at_phase"] == "build"
    assert rng["recorded_at"]


def test_review_ack_overwrites_with_the_latest_range(tmp_path, monkeypatch):
    """AC-4 + Q-001 'latest wins': one more real commit lands after the
    build-ack recording, and the review ack's OWN recording REPLACES the
    build-ack range with the new tip (not append-and-keep-both)."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-902"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    build_range = _read_meta(clone, ticket)["pre_merge_range"]

    _add_commit(clone, "widgets/thing.py", "a = 2\n", f"{ticket} step-2: change a")
    new_head = _rev_parse(clone, "HEAD")

    _set_phase(clone, ticket, "review:work")
    assert _run_ack(clone, ticket, "review", monkeypatch=monkeypatch, pick=1) == 0

    rng = _read_meta(clone, ticket)["pre_merge_range"]
    assert rng["head"] == new_head
    assert rng["head"] != build_range["head"]
    assert rng["recorded_at_phase"] == "review"
    assert rng["base"] == build_range["base"], "merge-base is unchanged, only head moves"


def test_manual_ack_overwrites_with_the_latest_range_on_an_m_track(tmp_path, monkeypatch):
    """AC-4, manual ack (M/L only per config/phases.yml): one more real commit
    after review, and the manual ack's recording again advances to its own
    tip."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-903"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _add_commit(clone, "widgets/thing.py", "a = 2\n", f"{ticket} step-2: change a")
    _set_phase(clone, ticket, "review:work")
    assert _run_ack(clone, ticket, "review", monkeypatch=monkeypatch, pick=1) == 0
    review_range = _read_meta(clone, ticket)["pre_merge_range"]

    _add_commit(clone, "widgets/thing.py", "a = 3\n", f"{ticket} step-3: change a again")
    new_head = _rev_parse(clone, "HEAD")
    _set_phase(clone, ticket, "manual:work")
    assert _run_ack(clone, ticket, "manual", monkeypatch=monkeypatch, pick=1) == 0

    rng = _read_meta(clone, ticket)["pre_merge_range"]
    assert rng["head"] == new_head
    assert rng["head"] != review_range["head"]
    assert rng["recorded_at_phase"] == "manual"


def test_empty_live_diff_at_a_recording_ack_does_not_clobber_the_prior_range(tmp_path, monkeypatch):
    """EDGE/negative twin for 'latest non-empty wins' (test-plan edge cases):
    a later recording ack whose OWN live diff happens to be empty (here: the
    ticket branch already got fast-forwarded into `main` by a quick self-merge
    before the review ack ran, so `merge-base(HEAD, origin/main)` now equals
    HEAD itself and the diff is empty) must NOT clobber the previously
    recorded (non-empty) range — the prior range survives untouched."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-904"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    build_range = _read_meta(clone, ticket)["pre_merge_range"]
    assert build_range["recorded_at_phase"] == "build"

    # Fast-forward main to the ticket tip and push — from now on, checked out
    # BACK on the ticket branch, the live merge-base diff is empty.
    _git(clone, "checkout", "main")
    _git(clone, "merge", "--ff-only", f"feature/{ticket}")
    _git(clone, "push", "origin", "main")
    _git(clone, "checkout", f"feature/{ticket}")

    _set_phase(clone, ticket, "review:work")
    assert _run_ack(clone, ticket, "review", monkeypatch=monkeypatch, pick=1) == 0

    rng = _read_meta(clone, ticket)["pre_merge_range"]
    assert rng == build_range, \
        "an empty live diff at a later recording ack must not overwrite the prior range"


@pytest.mark.parametrize("track,phase,output_name", [
    ("XS", "review-lite:work", "review-lite-report.md"),
    ("S", "review:work", "review-report.md"),
])
def test_track_skipped_ticket_records_no_range(tmp_path, monkeypatch, track, phase, output_name):
    """AC-4/Q-001 edge case (regression pin): a track whose integrate
    evaluators never run (XS at review-lite, or S with no escalation signal
    at review) never stages a `pre_merge_range`, regardless of a non-empty
    live diff."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-905"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase=phase, track=track,
                affected_modules=["widgets"], modules=_MODULES)

    pid = phase.split(":")[0]
    rc = _run_ack(clone, ticket, pid, monkeypatch=monkeypatch, pick=1)
    assert rc == 0

    meta = _read_meta(clone, ticket)
    assert "pre_merge_range" not in meta
