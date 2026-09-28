"""KLC-128 step-2 — the ground truth resolution order is live, THEN recorded
(AC-3): a non-empty live diff always wins, even when a recorded range also
exists and disagrees with it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _add_commit,
    _bare_and_clone,
    _branch_with_commits,
    _ground_truth,
    _run_ack,
    _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def test_non_empty_live_diff_wins_byte_identical_to_todays_behaviour(tmp_path, monkeypatch):
    """AC-3 positive: an UNMERGED ticket branch (live merge-base diff
    non-empty) resolves to exactly today's `_committed()` result, unaffected
    by whether a `pre_merge_range` also happens to be recorded."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-912"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc
    expected_mods, expected_paths = _pc._committed()

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "live-merge-base"
    assert gt["paths"] == expected_paths
    assert gt["modules"] == expected_mods
    assert expected_paths, "the live diff must be genuinely non-empty for this to test anything"


def test_live_diff_outranks_a_stale_recorded_range_even_when_they_differ(tmp_path, monkeypatch):
    """NEGATIVE/ordering twin: a recorded range from an EARLIER, smaller
    commit set exists in meta, but the branch has since grown WITHOUT another
    recording ack (so the recorded range stays stale/smaller) — the ground
    truth is the (larger) live diff, not the smaller stale recorded set. This
    proves 'live first' is an ORDERING rule, not a fallback-only-when-absent
    rule."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-913"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    # Grow the branch WITHOUT another recording ack — the recorded range stays
    # at its smaller, stale value.
    _add_commit(clone, "widgets/other.py", "b = 1\n", f"{ticket} step-2: add b")

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "live-merge-base"
    assert gt["paths"] == {"widgets/thing.py", "widgets/other.py"}
