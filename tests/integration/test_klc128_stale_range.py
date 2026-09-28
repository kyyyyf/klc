"""KLC-128 step-2 — D-001's accepted post-recording staleness window, pinned
as actual, asserted behaviour (test-plan edge cases), not silently assumed
away. Both directions are exercised against a REAL fixture repository.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _git,
    _ground_truth,
    _merge,
    _run_ack,
    _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def test_post_recording_commit_is_invisible_by_accepted_design(tmp_path, monkeypatch):
    """D-001 direction 1 (miss): a real commit lands on the ticket branch
    STRICTLY AFTER the last recording ack and BEFORE the merge (the
    documented 'Address any CI / reviewer blockers' Tick-1 action, F-014).
    The resolved ground truth does NOT include that commit's file — the
    accepted residual risk, asserted as actual behaviour."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-914"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    # A post-recording CI/reviewer fix, with no further recording ack.
    (clone / "widgets" / "late.py").write_text("late = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket}: address CI blocker")

    _merge(clone, ticket, "ff-only")

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "recorded-range"
    assert gt["paths"] == {"widgets/thing.py"}
    assert "widgets/late.py" not in gt["paths"], \
        "the post-recording commit is invisible by accepted design (D-001)"


def test_amend_after_recording_can_overcount_by_accepted_design(tmp_path, monkeypatch):
    """D-001 direction 2 (over-count): after the last recording ack, the
    commit it captured is AMENDED away (its object stays present in the local
    object database, merely unreachable from any live ref) before the
    eventual merge. The recorded-range diff resolves the now-dangling OLD
    head object exactly as before — the amended-away file's change STILL
    appears in the ground truth even though it was never actually merged.
    Explicitly asserted NOT to trigger the AC-8 degrade path: the shas are
    still resolvable in this clone, so this is not 'malformed'/'unreachable'."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-915"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    # Amend the recorded commit AWAY: drop widgets/thing.py, add widgets/other.py.
    _git(clone, "rm", "widgets/thing.py")
    (clone / "widgets").mkdir(parents=True, exist_ok=True)
    (clone / "widgets" / "other.py").write_text("b = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "--amend", "-m", f"{ticket} step-1: add b instead")

    _merge(clone, ticket, "ff-only")

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "recorded-range", \
        "the stale sha is still resolvable — this is not AC-8's degrade path"
    assert gt["reason"] is None
    assert gt["paths"] == {"widgets/thing.py"}, \
        "the amended-away file's change still appears — the accepted over-count (D-001)"
