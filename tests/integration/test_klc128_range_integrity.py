"""KLC-128 step-7 — review round 1 fixes (MEDIUM + LOW, AC-8/AC-12/AC-3):

(a) `_read_pre_merge_range`/`_resolve_ground_truth` must not accept ANY two
    resolvable 40-hex shas as a usable range — `base` must actually be an
    ANCESTOR of `head` in this repository's history. A crafted or mistaken
    pair of unrelated commits in `meta.json` (klc-state is multi-writer)
    must degrade, never silently become a `recorded-range` ground truth.

(b) `integrate_ground_truth`'s pre-warmed-cache branch (the KLC-110
    `cache["committed"]` shortcut) must short-circuit only on a NON-empty
    pre-warmed pair; an EMPTY one falls through to `_resolve_ground_truth`
    so the recorded range is still consulted, instead of prematurely
    reporting `source: "none"`.
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
    _run_ack,
    _seed_ticket,
    _set_phase,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def test_recorded_range_base_not_an_ancestor_of_head_degrades_with_a_named_reason(
    tmp_path, monkeypatch
):
    """AC-8/AC-12 (a): the ticket's OWN recorded range is real and resolvable
    (both shas exist in this clone), but `base` is a commit from an
    UNRELATED sibling branch — never an ancestor of the ticket's real head.
    The integrate ack degrades with a reason naming the failed ancestry
    check, never silently diffing two unrelated commits into a false
    ground truth."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-950"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])

    # A second, unrelated branch off the SAME main, sharing only the initial
    # commit as a common ancestor — never an ancestor of the ticket's head.
    _git(clone, "checkout", "main")
    _git(clone, "checkout", "-b", "feature/other")
    (clone / "other.py").write_text("x = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "unrelated commit")
    unrelated_head = _rev_parse(clone, "HEAD")
    _git(clone, "checkout", f"feature/{ticket}")
    ticket_head = _rev_parse(clone, "HEAD")

    _merge(clone, ticket, "ff-only")   # the live diff is now empty

    tdir = _seed_ticket(clone, ticket, phase="integrate:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES,
                       pre_merge_range={"base": unrelated_head, "head": ticket_head,
                                        "recorded_at_phase": "build",
                                        "recorded_at": "2026-01-01T00:00:00Z"})

    rc = _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1)
    assert rc == 0

    import json
    report = json.loads((tdir / "drift-report.json").read_text(encoding="utf-8"))
    assert report["ground_truth_source"] == "none"
    reason = report["scope_drift"]["skipped"] or ""
    assert "recorded pre-merge range base is not an ancestor of head" in reason


def test_pre_warmed_empty_committed_pair_falls_through_to_the_recorded_range(
    tmp_path, monkeypatch
):
    """AC-3 (b): `integrate_ground_truth`'s pre-warmed-cache branch must
    short-circuit only on a NON-EMPTY pre-warmed pair. A caller that
    pre-warms `cache["committed"]` with an EMPTY pair (e.g. it already
    resolved 'the live diff is empty' but never checked for a recorded
    range) must still get the recorded-range answer, not a premature
    `source: "none"`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-951"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "ff-only")
    _set_phase(clone, ticket, "integrate:work")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import phase_completion as _pc

    gt = _pc.integrate_ground_truth(ticket, cache={"committed": (set(), set())})
    assert gt["source"] == "recorded-range"
    assert gt["paths"] == {"widgets/thing.py"}
