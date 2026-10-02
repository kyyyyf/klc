"""KLC-166 step-1 — `phase_completion.ticket_diff_range(ticket)`, the ONE
composed range rule the hand-back planner bootstrap (step-2) will call: the
ticket's own committed range, live first (merge-base of HEAD with
`origin/main`, else `main`, up to HEAD, gated on `_head_branch_mismatch` and
on the live diff touching at least one path outside `.klc/`), then the
recorded `meta.pre_merge_range` (KLC-128 SHA/ancestry/non-empty checks),
otherwise no range at all with a reason naming both legs.

Eight tests on real temporary git repositories, one per row of
`design/options.md`'s AC-1/AC-2/AC-3 decision table (D-010). Every test
drives `phase_completion.ticket_diff_range` directly (not through an ack),
with `PROJECT_ROOT` pointed at a temporary clone via `monkeypatch.setenv` —
no test reads or writes the live `.klc/tickets` tree (C-005).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _git,
    _merge,
    _rev_parse,
    _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def _range(clone: Path, ticket: str, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc
    return _pc.ticket_diff_range(ticket)


def test_live_range_on_the_tickets_own_branch_uses_the_origin_main_merge_base(
    tmp_path, monkeypatch
):
    """AC-1: HEAD on the ticket's own branch, `origin/main` present. The live
    range is `merge-base(HEAD, origin/main)..HEAD`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-960"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch="feature/klc-960-add-a-widget")
    head = _rev_parse(clone, "HEAD")
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    rng, why = _range(clone, ticket, monkeypatch)
    assert why == ""
    assert rng == {"base": base, "head": head, "source": "live-merge-base"}


def test_live_range_falls_back_to_local_main_when_origin_is_absent(tmp_path, monkeypatch):
    """AC-1: with no `origin` remote configured at all, the live range falls
    back to the merge-base with the local `main` branch."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-961"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch="feature/klc-961-add-a-widget")
    head = _rev_parse(clone, "HEAD")
    _git(clone, "remote", "remove", "origin")
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    rng, why = _range(clone, ticket, monkeypatch)
    assert why == ""
    assert rng == {"base": base, "head": head, "source": "live-merge-base"}


def test_recorded_range_used_when_head_is_on_another_tickets_branch(tmp_path, monkeypatch):
    """AC-2 (trigger 1): HEAD is on a DIFFERENT ticket's branch
    (`feature/klc-991-other`, naming KLC-991) while resolving KLC-990's
    range. The live diff is never trusted; the recorded range is used
    instead, and its `diff_sha256` precondition is the materialised
    `git diff <base> <head>` of the RECORDED pair, not the live branch."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-990"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket_a, [
        ("widgets/thing.py", "a = 1\n", f"{ticket_a} step-1: add a"),
    ], branch="feature/klc-990-add-a-widget")
    head = _rev_parse(clone, "HEAD")
    _seed_ticket(clone, ticket_a, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES,
                pre_merge_range={"base": base, "head": head,
                                 "recorded_at_phase": "build",
                                 "recorded_at": "2026-01-01T00:00:00Z"})

    ticket_b = "KLC-991"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-991-other")

    rng, why = _range(clone, ticket_a, monkeypatch)
    assert why == ""
    assert rng == {"base": base, "head": head, "source": "recorded-range"}


def test_recorded_range_used_when_the_live_range_touches_only_dot_klc_paths(
    tmp_path, monkeypatch
):
    """AC-2 (trigger 3): HEAD is on the ticket's own branch and a merge-base
    IS computable, but the live range's only changed path is under `.klc/`
    — an in-band ack-artefact commit with nothing else. That must not count
    as a usable live range; the recorded range is used instead.

    Built so the live diff (merge-base(HEAD, origin/main)..HEAD) is EXACTLY
    the `.klc/`-only commit: the widgets commit is first merged `--ff-only`
    into `main` and pushed, so `origin/main` already sits at it; only THEN
    is the `.klc/`-only commit added on top, locally, never pushed."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-962"
    recorded_base = _rev_parse(clone, "main")
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    recorded_head = _rev_parse(clone, "HEAD")
    _merge(clone, ticket, "ff-only")           # origin/main now == recorded_head
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES,
                pre_merge_range={"base": recorded_base, "head": recorded_head,
                                 "recorded_at_phase": "build",
                                 "recorded_at": "2026-01-01T00:00:00Z"})
    # one more commit on top of main, touching only .klc/, NEVER pushed — the
    # live range (merge-base == origin/main == recorded_head, up to HEAD) has
    # no path outside .klc/, so it must be rejected as unusable.
    (clone / ".klc" / "tickets" / ticket).mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "tickets" / ticket / "note.md").write_text("note\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket}: ack artefact only")

    rng, why = _range(clone, ticket, monkeypatch)
    assert why == ""
    assert rng == {"base": recorded_base, "head": recorded_head, "source": "recorded-range"}


def test_recorded_range_used_when_no_merge_base_is_computable(tmp_path, monkeypatch):
    """AC-2 (trigger 2, spec-review F-6 / test-plan-review F-1): HEAD sits on
    an ORPHAN branch sharing no history at all with `main` or `origin/main`,
    so neither merge-base lookup resolves. With a valid recorded range
    present, the resolver falls through to it — this is a SUCCESS path, not
    AC-3's all-unusable path."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-963"
    recorded_base = _rev_parse(clone, "main")
    _git(clone, "checkout", "main")
    (clone / "widgets").mkdir(parents=True, exist_ok=True)
    (clone / "widgets" / "thing.py").write_text("a = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket} step-1: add a")
    recorded_head = _rev_parse(clone, "HEAD")
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES,
                pre_merge_range={"base": recorded_base, "head": recorded_head,
                                 "recorded_at_phase": "build",
                                 "recorded_at": "2026-01-01T00:00:00Z"})

    _git(clone, "checkout", "--orphan", "feature/klc-963-orphan")
    _git(clone, "rm", "-rf", "--cached", ".")
    (clone / "orphan.txt").write_text("o\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket} orphan: unrelated history")

    rng, why = _range(clone, ticket, monkeypatch)
    assert why == ""
    assert rng == {"base": recorded_base, "head": recorded_head, "source": "recorded-range"}


def test_no_range_names_the_branch_mismatch_and_the_missing_recorded_range(
    tmp_path, monkeypatch
):
    """AC-3: HEAD on a different ticket's branch, and no recorded range at
    all for the acked ticket. The exact reason names both legs."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-990"
    _seed_ticket(clone, ticket_a, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    ticket_b = "KLC-991"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-991-other")

    rng, why = _range(clone, ticket_a, monkeypatch)
    assert rng is None
    assert why == (
        "HEAD is on 'feature/klc-991-other', which names ['KLC-991'], not KLC-990; "
        "no recorded pre-merge range for this ticket"
    )


def test_no_range_when_the_recorded_base_is_not_an_ancestor_of_head(tmp_path, monkeypatch):
    """AC-3: live fails (HEAD on another ticket's branch) and the recorded
    range's `base`/`head` pair is NOT an ancestor relationship (a crafted or
    mistaken pair) — never silently trusted as a ground truth (KLC-128
    step-7)."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-990"
    base = _rev_parse(clone, "main")
    _git(clone, "checkout", "main")
    (clone / "widgets").mkdir(parents=True, exist_ok=True)
    (clone / "widgets" / "thing.py").write_text("a = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", f"{ticket_a} step-1: add a")
    head = _rev_parse(clone, "HEAD")
    # reversed pair: head is NOT an ancestor of base
    _seed_ticket(clone, ticket_a, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES,
                pre_merge_range={"base": head, "head": base,
                                 "recorded_at_phase": "build",
                                 "recorded_at": "2026-01-01T00:00:00Z"})

    ticket_b = "KLC-991"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-991-other")

    rng, why = _range(clone, ticket_a, monkeypatch)
    assert rng is None
    assert "not an ancestor of head" in why
    assert "KLC-991" in why


def test_no_range_when_the_recorded_range_is_malformed(tmp_path, monkeypatch):
    """AC-3: live fails (HEAD on another ticket's branch) and the recorded
    range is malformed (missing `head`) — reported as a specific reason, not
    a bare generic skip."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-990"
    base = _rev_parse(clone, "main")
    _seed_ticket(clone, ticket_a, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES,
                pre_merge_range={"base": base,
                                 "recorded_at_phase": "build",
                                 "recorded_at": "2026-01-01T00:00:00Z"})

    ticket_b = "KLC-991"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ], branch="feature/klc-991-other")

    rng, why = _range(clone, ticket_a, monkeypatch)
    assert rng is None
    assert "malformed" in why
    assert "KLC-991" in why
