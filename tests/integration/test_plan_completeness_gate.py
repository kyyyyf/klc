"""KLC-036 step-2/3: plan-completeness gate at discovery-lite (S) and design (M/L).

Gate: if impl-plan.md exists and contains a step with a violation
(missing required field, placeholder token, empty fence, or no code sketch),
the ack must be blocked.  A clean plan (or no impl-plan.md at all) must pass.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.phase_completion import (  # noqa: E402
    can_complete_discovery_lite,
    can_complete,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_S_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
risk_tags: []
---

## Goals
Add a plan-completeness gate so incomplete impl-plans are caught at ack.

## Acceptance Criteria
- [ ] AC-1: Dirty impl-plan blocks discovery-lite ack.
- [ ] AC-2: Clean impl-plan allows ack.

## Affected
phase_completion: core/skills/phase_completion.py, src=core/skills/phase_completion.py:1

## Estimate
complexity: 1
uncertainty: 1
risk: 1
manual: 0
total: 3
"""

_VALID_M_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
risk_tags: []
---

## Goals
Add plan-completeness gate for M-track design ack.

## Acceptance Criteria
- [ ] AC-1: Dirty impl-plan blocks design ack.
- [ ] AC-2: Clean impl-plan allows design ack.

## Affected
phase_completion: core/skills/phase_completion.py, src=core/skills/phase_completion.py:1

## Estimate
complexity: 2
uncertainty: 1
risk: 1
manual: 0
total: 4
"""

_OPTIONS_LITE_VALID = """\
## Approach options
- Option A: inline scanner — add impl_plan_check call directly in phase_completion
- Option B: separate hook — call from ack.py pre-ack hook

Picked: Option A — minimal coupling, no new hook surface
"""

_DIRTY_IMPL_PLAN = """\
# Implementation plan — {ticket}

## step-1 — implement helper
**Goal:** add the helper function
**VERIFY:** `pytest tests/ -q`
**COMMIT:** `{ticket} step-1: add helper`
**Affected:** module.py
"""

_CLEAN_IMPL_PLAN = """\
# Implementation plan — {ticket}

## step-1 — implement helper
**Goal:** add the helper function
**RED:** not applicable — config-only change
**GREEN:** update config
**VERIFY:** `pytest tests/ -q`
**Expected:** 1 passed
**COMMIT:** `{ticket} step-1: add helper`
**Affected:** module.py
**Interfaces:** none
**Depends-on:** none
"""


def _make_s_ticket(tmp_path: Path, ticket: str, impl_plan: str | None = None) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery-lite:ack-needed",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "affected_modules": ["phase_completion"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(_VALID_S_SPEC.format(ticket=ticket), encoding="utf-8")
    (ticket_dir / "options-lite.md").write_text(_OPTIONS_LITE_VALID, encoding="utf-8")
    if impl_plan is not None:
        (ticket_dir / "impl-plan.md").write_text(
            impl_plan.format(ticket=ticket), encoding="utf-8"
        )
    return ticket_dir


def _make_m_ticket(tmp_path: Path, ticket: str, impl_plan: str | None = None) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "design:ack-needed",
        "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "affected_modules": ["phase_completion"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(_VALID_M_SPEC.format(ticket=ticket), encoding="utf-8")
    design_dir = ticket_dir / "design"
    design_dir.mkdir()
    # minimal options.md so generic design gate passes
    (design_dir / "options.md").write_text(
        "- Option A: inline\n- Option B: hook\nPicked: Option A\n", encoding="utf-8"
    )
    if impl_plan is not None:
        (ticket_dir / "impl-plan.md").write_text(
            impl_plan.format(ticket=ticket), encoding="utf-8"
        )
    return ticket_dir


# ---------------------------------------------------------------------------
# Step-2: discovery-lite (S) gate
# ---------------------------------------------------------------------------

def test_dirty_impl_plan_blocks_discovery_lite(tmp_path, monkeypatch):
    """S-track impl-plan with missing fields blocks discovery-lite ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_s_ticket(tmp_path, "KLC-PC01", impl_plan=_DIRTY_IMPL_PLAN)
    ok, msg = can_complete_discovery_lite("KLC-PC01")
    assert not ok, "expected False for dirty impl-plan"
    assert "impl-plan.md" in msg, f"expected 'impl-plan.md' in msg, got: {msg!r}"


def test_clean_impl_plan_passes_discovery_lite(tmp_path, monkeypatch):
    """S-track impl-plan with all required fields passes discovery-lite ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_s_ticket(tmp_path, "KLC-PC02", impl_plan=_CLEAN_IMPL_PLAN)
    ok, msg = can_complete_discovery_lite("KLC-PC02")
    assert ok, f"expected True for clean impl-plan, got: {msg!r}"


def test_no_impl_plan_passes_discovery_lite(tmp_path, monkeypatch):
    """Missing impl-plan.md does not block (plan authored later for XS/S)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_s_ticket(tmp_path, "KLC-PC03", impl_plan=None)
    ok, msg = can_complete_discovery_lite("KLC-PC03")
    assert ok, f"expected True when no impl-plan.md, got: {msg!r}"


# ---------------------------------------------------------------------------
# Step-3: design (M/L) gate
# ---------------------------------------------------------------------------

def test_dirty_impl_plan_blocks_design_ack(tmp_path, monkeypatch):
    """M-track impl-plan with missing fields blocks design ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_m_ticket(tmp_path, "KLC-PC04", impl_plan=_DIRTY_IMPL_PLAN)
    ok, msg = can_complete("KLC-PC04", "design")
    assert not ok, "expected False for dirty impl-plan on design ack"
    assert "impl-plan.md" in msg, f"expected 'impl-plan.md' in msg, got: {msg!r}"


def test_clean_impl_plan_passes_design_ack(tmp_path, monkeypatch):
    """M-track impl-plan with all required fields passes design ack."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_m_ticket(tmp_path, "KLC-PC05", impl_plan=_CLEAN_IMPL_PLAN)
    ok, msg = can_complete("KLC-PC05", "design")
    assert ok, f"expected True for clean impl-plan on design ack, got: {msg!r}"


def test_missing_impl_plan_blocks_design_ack(tmp_path, monkeypatch):
    """M-track design ack requires impl-plan.md (phases.yml output); missing → blocked."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_m_ticket(tmp_path, "KLC-PC06", impl_plan=None)
    ok, msg = can_complete("KLC-PC06", "design")
    assert not ok, "expected False when impl-plan.md is absent at design ack"
    assert "impl-plan.md" in msg.lower(), f"expected impl-plan.md in msg, got: {msg!r}"
