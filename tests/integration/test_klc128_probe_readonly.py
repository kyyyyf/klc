"""KLC-128 step-1 — a read-only probe (`persist=False`) never stages a
`pre_merge_range`, and leaves `meta.json` byte-identical (AC-5)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _meta_bytes,
    _read_meta,
    _run_ack,
    _seed_ticket,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}]


def test_remind_probe_at_build_leaves_meta_byte_identical(tmp_path, monkeypatch):
    """AC-5: the real read-only probe path (`persist=False`, the exact call
    shape `klc remind` / gate-policy advisory collection use,
    `core/phases/remind.py:124`) at the build phase leaves `meta.json` bytes
    unchanged and stages no `pre_merge_range` — then, as a positive control,
    the real persisting `ack.run` DOES record one."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-906"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    before = _meta_bytes(clone, ticket)
    ok, _msg = _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, persist=False)
    after = _meta_bytes(clone, ticket)

    assert before == after, "a read-only probe must leave meta.json byte-identical"
    assert "pre_merge_range" not in _read_meta(clone, ticket)

    # Positive control: the real persisting ack DOES record a range.
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    assert "pre_merge_range" in _read_meta(clone, ticket)


@pytest.mark.parametrize("phase", ["review", "manual"])
def test_remind_probe_at_review_and_manual_leaves_meta_byte_identical(tmp_path, monkeypatch, phase):
    """AC-5, parametrized over review and manual (the other two
    recording-capable acks per Q-001) — same byte-identical assertion, plus
    the same positive control."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-907"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase=f"{phase}:work", track="M",
                affected_modules=["widgets"], modules=_MODULES)

    before = _meta_bytes(clone, ticket)
    ok, _msg = _run_ack(clone, ticket, phase, monkeypatch=monkeypatch, persist=False)
    after = _meta_bytes(clone, ticket)

    assert before == after, "a read-only probe must leave meta.json byte-identical"
    assert "pre_merge_range" not in _read_meta(clone, ticket)

    assert _run_ack(clone, ticket, phase, monkeypatch=monkeypatch, pick=1) == 0
    assert "pre_merge_range" in _read_meta(clone, ticket)
