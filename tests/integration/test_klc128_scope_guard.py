"""KLC-128 step-5 — AC-14 (Q-002 'share the ground truth, keep the blocking
rule'): the integrate scope guard in `core/phases/ack.py` uses the SAME
shared ground truth as the drift check and the retrieval evaluator, and so
can again block an already-merged ticket whose recorded range touches an
unplanned module."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _merge,
    _run_ack,
    _seed_ticket,
    _set_phase,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}, {"name": "gadgets", "path": "gadgets/"}]


def test_integrate_scope_guard_blocks_a_merged_ticket_whose_recorded_range_has_an_unplanned_module(
    tmp_path, monkeypatch, capsys
):
    """AC-14 positive: merged ff-only ticket, recorded range includes a file
    under a module NOT in `meta.affected_modules` — the real `ack.py`
    integrate scope guard (driven through the public `ack.run` CLI entry
    point, not `can_complete` directly) blocks with the unplanned module
    named, using the SAME recorded-range ground truth AC-6 verified — not
    the pre-fix skipped-therefore-blind behaviour (F-005).

    KLC-128 step-8 (review MEDIUM): at integrate the ticket is ALREADY
    MERGED, so 'use `klc jump` to restart review' (review's own wording) is
    actively misleading here — the message must instead say the ticket is
    merged and point at `klc scope-fix`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-940"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
        ("gadgets/extra.py", "b = 1\n", f"{ticket} step-1: add an unplanned file"),
    ])
    # affected_modules deliberately omits "gadgets" — an unplanned module.
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "ff-only")
    _set_phase(clone, ticket, "integrate:work")

    capsys.readouterr()  # discard everything captured so far (the build ack's own noise)
    rc = _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1)
    err = capsys.readouterr().err

    assert rc == 1
    assert "already merged" in err
    assert "klc jump" not in err
    assert "restart review" not in err
    assert "klc scope-fix" in err
    assert ticket in err


def test_integrate_scope_guard_does_not_block_a_merged_ticket_within_plan(tmp_path, monkeypatch):
    """AC-14 negative twin: same fixture, but the recorded range's files are
    ALL within `meta.affected_modules` — the integrate ack proceeds (no
    block), proving the positive case above isn't a vacuous always-block."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-941"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0

    _merge(clone, ticket, "ff-only")
    _set_phase(clone, ticket, "integrate:work")

    rc = _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1)

    assert rc == 0
