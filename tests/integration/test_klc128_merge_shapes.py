"""KLC-128 step-2 — the resolved ground truth matches the pre-merge file set
after every named merge shape (AC-1, AC-2), driven against a REAL fixture
repository (a real `git merge --ff-only|--no-ff|--squash`, or a real
`git rebase` before an `--ff-only` merge), never a canned diff.
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


def test_ff_only_merge_ground_truth_equals_pre_merge_files(tmp_path, monkeypatch):
    """AC-1: build a ticket branch (whose commits also touch a
    `.klc/tickets/<KEY>/note.md` in-band artefact file, which must NOT leak
    into the ground truth, per the edge-case list), record at the build ack,
    `git merge --ff-only` + push, then resolve the ground truth — it must
    equal the branch's own pre-merge changed files minus `.klc/` paths."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-908"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
        (f".klc/tickets/{ticket}/note.md", "an in-band ack artefact\n",
         f"{ticket} step-1: note"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "ff-only")

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "recorded-range"
    assert gt["paths"] == {"widgets/thing.py"}
    assert gt["modules"] == {"widgets"}


def test_no_ff_merge_commit_ground_truth_matches_pre_merge_files(tmp_path, monkeypatch):
    """AC-2, shape 1/2: same fixture, merged with `git merge --no-ff` (a real
    merge commit) — the ground truth is unaffected by the extra merge
    commit."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-909"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "no-ff")

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "recorded-range"
    assert gt["paths"] == {"widgets/thing.py"}


def test_squash_merge_with_key_less_subject_ground_truth_matches_pre_merge_files(tmp_path, monkeypatch):
    """AC-2, shape 2/2: `git merge --squash` with a commit subject that
    deliberately does NOT contain the ticket key (F-011's forge-default
    reproduction) — the ground truth still matches, proving the derivation
    never depended on grepping the commit subject."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-910"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", "add a"),
        ("widgets/thing.py", "a = 2\n", "review-fix: tweak a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "squash")

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "recorded-range"
    assert gt["paths"] == {"widgets/thing.py"}


def test_pre_merge_rebase_then_ff_ground_truth_matches_final_branch_state(tmp_path, monkeypatch):
    """The fourth named merge shape (options.md Option B pros): the ticket
    branch is rebased onto an ADVANCED `main` BEFORE its last recording ack
    runs, then `--ff-only` merged — the ground truth matches the POST-rebase
    file state (the recording ack, run after the rebase, captured the true
    final shas), not a stale pre-rebase set."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-911"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])

    # main advances independently (an unrelated ticket merges first).
    _git(clone, "checkout", "main")
    _git(clone, "add", "-A")
    (clone / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "KLC-999: unrelated change")
    _git(clone, "push", "origin", "main")

    # The ticket branch is rebased onto the new main BEFORE the recording ack.
    _git(clone, "checkout", f"feature/{ticket}")
    _git(clone, "rebase", "main")

    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "ff-only")

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "recorded-range"
    assert gt["paths"] == {"widgets/thing.py"}, \
        "unrelated.py belongs to main's own history, not this ticket's range"
