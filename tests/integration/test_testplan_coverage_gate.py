#!/usr/bin/env python3
"""Integration: the KLC-085 test-plan review wired into
can_complete_acceptance_test_plan.

Two layers are surfaced at the ack, both warn-only (never a new blocking gate):
  * the DETERMINISTIC coverage gate (`testplan-review[...]` advisories) — 085's
    own AC→test heuristics; an uncovered AC is surfaced, not blocked.
  * the INDEPENDENT reviewer verdict (`test-plan-review[...]` advisories) — reuses
    KLC-084's generic seam bound to `TEST_PLAN_REVIEW`; its findings are recorded
    to `test-plan-review-findings.json` ONLY on the persisting (ack) path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.phase_completion import (  # noqa: E402
    can_complete,
    can_complete_acceptance_test_plan,
)

# A clean independent-reviewer verdict (empty findings + decisions) so the seam
# layer is silent and only the deterministic layer is under test where relevant.
_CLEAN_REVIEW = '```json\n{"findings":[],"decisions_to_confirm":[]}\n```\n'
# A verdict with one finding, to check the ack persists it and a probe does not.
_REVIEW_WITH_FINDING = (
    '```json\n{"findings":[{"id":"F-1","category":"missing-edge-case",'
    '"severity":"high","detail":"AC-2 gate has no negative case"}],'
    '"decisions_to_confirm":[]}\n```\n'
)

_SPEC = """\
---
ticket: {ticket}
kind: feature
track: M
---

## Goals
Ship the coverage review.

## Acceptance Criteria
1. AC-1: the review · maps · each AC to a planned test · when it reviews a test-plan
2. AC-2: the gate · rejects · a spec AC with no test · when the coverage table omits it
"""

_PLAN_UNCOVERED = """\
---
ticket: {ticket}
authority: hybrid
---

# Test plan — {ticket}

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_maps | — |
| AC-2 | acceptance | — | TBD |

## Edge cases
- an uncovered AC is flagged as a finding
"""

_PLAN_FULL = """\
---
ticket: {ticket}
authority: hybrid
---

# Test plan — {ticket}

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | acceptance | tests/test_map.py::test_maps | — |
| AC-2 | acceptance | tests/test_gate.py::test_rejects_uncovered | negative: missing test |

## Edge cases
- an uncovered AC is flagged; an empty plan degrades rather than crashing
"""


def _make(tmp_path: Path, ticket: str, plan: str, *, review: str | None = None,
          track: str = "M") -> Path:
    d = tmp_path / ".klc" / "tickets" / ticket
    d.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "feature",
            "phase": "acceptance-test-plan:work", "track": track}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "spec.md").write_text(_SPEC.format(ticket=ticket), encoding="utf-8")
    (d / "test-plan.md").write_text(plan.format(ticket=ticket), encoding="utf-8")
    if review is not None:
        (d / "test-plan-review.md").write_text(review, encoding="utf-8")
    return d


def test_uncovered_ac_surfaced_but_not_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    # Clean independent verdict so the deterministic coverage layer is isolated.
    _make(tmp_path, "KLC-T01", _PLAN_UNCOVERED, review=_CLEAN_REVIEW)
    ok, msg = can_complete_acceptance_test_plan("KLC-T01")
    assert ok, "coverage review must not add a new blocking gate"
    assert "AC-2" in msg and "testplan-review" in msg


def test_fully_covered_plan_passes_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    # Both layers clean: covered plan + empty reviewer verdict → no advisory at all.
    _make(tmp_path, "KLC-T02", _PLAN_FULL, review=_CLEAN_REVIEW)
    ok, msg = can_complete_acceptance_test_plan("KLC-T02")
    assert ok
    assert "testplan-review" not in msg, f"expected clean deterministic, got: {msg!r}"
    assert "test-plan-review" not in msg, f"expected clean seam, got: {msg!r}"


def test_independent_reviewer_verdict_surfaced_at_ack(tmp_path, monkeypatch):
    # The independent reviewer's findings (084 seam) are surfaced with the
    # test-plan-review label and recorded to disk on the persisting ack path.
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _make(tmp_path, "KLC-T03", _PLAN_FULL, review=_REVIEW_WITH_FINDING)
    ok, msg = can_complete_acceptance_test_plan("KLC-T03")
    assert ok
    assert "test-plan-review" in msg and "finding(s) recorded" in msg
    assert (d / "test-plan-review-findings.json").exists()


def test_readonly_probe_surfaces_without_writing(tmp_path, monkeypatch):
    # persist=False (via can_complete, the gate-policy / remind path) surfaces the
    # same advisory but must NOT write test-plan-review-findings.json (KLC-062).
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _make(tmp_path, "KLC-T04", _PLAN_FULL, review=_REVIEW_WITH_FINDING)
    ok, msg = can_complete("KLC-T04", "acceptance-test-plan", persist=False)
    assert ok
    assert "test-plan-review" in msg  # still surfaced
    assert not (d / "test-plan-review-findings.json").exists()  # but not written


def test_readonly_probe_does_not_migrate_legacy_meta(tmp_path, monkeypatch):
    # FIX-1: the deterministic coverage gate reads the track on the probe path too.
    # If it used the migrating reader, a persist=False probe against a ticket whose
    # meta.json carries a LEGACY phase string would silently rewrite meta.json.
    # A read-only probe must leave meta.json byte-for-byte unchanged (KLC-062).
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-T05"
    d = tmp_path / ".klc" / "tickets" / ticket
    d.mkdir(parents=True)
    meta_file = d / "meta.json"
    # "test-plan-pending" is the legacy form of "acceptance-test-plan:work".
    meta_file.write_text(
        json.dumps({"ticket": ticket, "kind": "feature",
                    "phase": "test-plan-pending", "track": "M"}),
        encoding="utf-8",
    )
    (d / "spec.md").write_text(_SPEC.format(ticket=ticket), encoding="utf-8")
    (d / "test-plan.md").write_text(_PLAN_FULL.format(ticket=ticket), encoding="utf-8")
    (d / "test-plan-review.md").write_text(_CLEAN_REVIEW, encoding="utf-8")

    before = meta_file.read_bytes()
    ok, _msg = can_complete(ticket, "acceptance-test-plan", persist=False)
    assert ok
    assert meta_file.read_bytes() == before, "probe must not migrate/rewrite meta.json"
