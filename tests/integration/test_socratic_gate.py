"""Tests for core/skills/spec_structure.py helpers (KLC-032 steps 1 + 2)."""
import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))  # for bare imports inside phase_completion

from core.skills import spec_structure  # noqa: E402
import tests.prompt_harness as prompt_harness  # noqa: E402
from core.skills.phase_completion import (  # noqa: E402
    can_complete_discovery_lite,
    can_complete_discovery,
)

# ---------------------------------------------------------------------------
# Step-1: helpers
# ---------------------------------------------------------------------------

def test_helpers_importable_and_shared():
    """has_min_approaches re-exported from harness must be the same object as spec_structure's."""
    assert prompt_harness.has_min_approaches is spec_structure.has_min_approaches


def test_recorded_pick_detects_picked_marker():
    assert spec_structure.recorded_pick("Picked: Option A — lower coupling")


def test_recorded_pick_detects_decision_marker():
    assert spec_structure.recorded_pick("DECISION D-001: use clangd backend")


def test_recorded_pick_rejects_prose():
    assert not spec_structure.recorded_pick("We will pick the best option.")
    assert not spec_structure.recorded_pick("pick any approach you like")


def test_recorded_pick_rejects_placeholder():
    assert not spec_structure.recorded_pick("Picked: <approach>")
    assert not spec_structure.recorded_pick("Picked: <chosen option>")
    assert not spec_structure.recorded_pick("Picked: TBD")
    assert not spec_structure.recorded_pick("Picked: tbd")
    assert not spec_structure.recorded_pick("Picked:")
    assert not spec_structure.recorded_pick("Picked:   ")


def test_recorded_pick_accepts_concrete():
    assert spec_structure.recorded_pick("Picked: Option A — reason")
    assert spec_structure.recorded_pick("Picked: Option A — reason   ")  # trailing whitespace
    assert spec_structure.recorded_pick("DECISION D-001")                # decision-only spec


# ---------------------------------------------------------------------------
# Step-2: gate fixtures
# ---------------------------------------------------------------------------

_VALID_S_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
risk_tags: []
---

## Goals
Provide a concrete implementation for the required feature.

## Acceptance Criteria
- [ ] AC-1: The gate blocks discovery-lite ack when options-lite.md lacks two approaches.
- [ ] AC-2: The gate passes when options-lite.md has two or more approaches and a recorded pick.

## Affected
test_module: core/test.py, src=core/test.py:1

## Estimate
complexity: 1
uncertainty: 1
risk: 1
manual: 0
total: 3
"""

_VALID_XS_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
risk_tags: []
---

## Goals
Provide a concrete implementation for the required XS feature.

## Acceptance Criteria
- [ ] AC-1: The system does X when Y is present.

## Affected
test_module: core/test.py, src=core/test.py:1

## Estimate
complexity: 0
uncertainty: 1
risk: 0
manual: 0
total: 1
"""

_VALID_M_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
---

## Goals
Provide a concrete implementation for the required M-track feature.

## Acceptance Criteria
- [ ] AC-1: The system does X when Y is present.

## Estimate
complexity: 2
uncertainty: 1
risk: 1
manual: 0
total: 4
"""


_GATE_PASSING_IMPL_PLAN = """\
## step-1 — do the thing

- **Goal:** implement the feature
- RED: not applicable
- **Interfaces:** `def f() -> None`
- **Expected:** f runs
- **VERIFY:** pytest
- **COMMIT:** KLC-X step-1: do the thing
- **Affected:** src/x.py
"""


def _make_s_ticket(tmp_path: Path, ticket: str) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery-lite:work",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "affected_modules": ["test_module"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(_VALID_S_SPEC.format(ticket=ticket), encoding="utf-8")
    (ticket_dir / "impl-plan.md").write_text(_GATE_PASSING_IMPL_PLAN, encoding="utf-8")
    return ticket_dir


def _make_xs_ticket(tmp_path: Path, ticket: str) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery-lite:work",
        "track": "XS",
        "estimate": {"complexity": 0, "uncertainty": 1, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["test_module"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(_VALID_XS_SPEC.format(ticket=ticket), encoding="utf-8")
    return ticket_dir


def _make_m_ticket(tmp_path: Path, ticket: str) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery:work",
        "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "affected_modules": ["test_module"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return ticket_dir


def test_gate_blocks_missing_approaches_or_pick(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    # Case 1: < 2 approaches → blocked
    d1 = _make_s_ticket(tmp_path, "KLC-G01")
    (d1 / "options-lite.md").write_text("- Option A: fast impl\n", encoding="utf-8")
    ok, msg = can_complete_discovery_lite("KLC-G01")
    assert not ok, "expected False with only 1 approach"
    assert "approach" in msg.lower(), f"expected 'approach' in msg, got: {msg!r}"

    # Case 2: ≥2 approaches but no pick → blocked
    d2 = _make_s_ticket(tmp_path, "KLC-G02")
    (d2 / "options-lite.md").write_text(
        "- Option A: fast impl\n- Option B: safer impl\n", encoding="utf-8"
    )
    ok2, msg2 = can_complete_discovery_lite("KLC-G02")
    assert not ok2, "expected False with approaches but no pick"
    assert "pick" in msg2.lower(), f"expected 'pick' in msg, got: {msg2!r}"

    # Case 3: ≥2 approaches + pick → passes
    d3 = _make_s_ticket(tmp_path, "KLC-G03")
    (d3 / "options-lite.md").write_text(
        "- Option A: fast impl\n- Option B: safer impl\nPicked: Option A — lower risk\n",
        encoding="utf-8",
    )
    ok3, msg3 = can_complete_discovery_lite("KLC-G03")
    assert ok3, f"expected True for complete S-ticket, got: {msg3!r}"

    # Case 4: XS ticket with no options-lite.md → passes (exempt)
    _make_xs_ticket(tmp_path, "KLC-G04")
    ok4, msg4 = can_complete_discovery_lite("KLC-G04")
    assert ok4, f"expected True for XS-ticket (exempt), got: {msg4!r}"


def test_m_gate_blocks_missing_approaches_or_pick(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    # M-track with no approaches in spec.md → blocked
    d = _make_m_ticket(tmp_path, "KLC-M01")
    (d / "spec.md").write_text(
        _VALID_M_SPEC.format(ticket="KLC-M01"), encoding="utf-8"
    )
    ok, msg = can_complete_discovery("KLC-M01")
    assert not ok, "expected False for M-track spec with no approaches"
    assert "approach" in msg.lower(), f"expected 'approach' in msg, got: {msg!r}"

    # M-track with approaches + pick in spec.md → passes
    d2 = _make_m_ticket(tmp_path, "KLC-M02")
    spec_with_pick = (
        _VALID_M_SPEC.format(ticket="KLC-M02")
        + "\n- Option A: fast impl\n- Option B: safer impl\n\nPicked: Option A — lower risk\n"
    )
    (d2 / "spec.md").write_text(spec_with_pick, encoding="utf-8")
    ok2, msg2 = can_complete_discovery("KLC-M02")
    assert ok2, f"expected True for M-track spec with approaches+pick, got: {msg2!r}"


# ---------------------------------------------------------------------------
# Step-3: DISCOVERY_DECOMPOSE advisory
# ---------------------------------------------------------------------------

def test_decompose_signal_helper():
    assert spec_structure.has_decompose_signal("DISCOVERY_DECOMPOSE")
    assert spec_structure.has_decompose_signal("Emitting DISCOVERY_DECOMPOSE here.")
    assert not spec_structure.has_decompose_signal("No signal here")


def test_decompose_signal_recognized(tmp_path, monkeypatch):
    """DISCOVERY_DECOMPOSE in spec.md is non-blocking but surfaces an advisory note."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    d = _make_s_ticket(tmp_path, "KLC-D01")
    (d / "spec.md").write_text(
        _VALID_S_SPEC.format(ticket="KLC-D01") + "\nDISCOVERY_DECOMPOSE\n",
        encoding="utf-8",
    )
    (d / "options-lite.md").write_text(
        "- Option A: fast impl\n- Option B: safer impl\nPicked: Option A — lower risk\n",
        encoding="utf-8",
    )
    ok, msg = can_complete_discovery_lite("KLC-D01")
    assert ok, f"DISCOVERY_DECOMPOSE must not block ack, got: {msg!r}"
    assert "DISCOVERY_DECOMPOSE" in msg, f"expected advisory note in msg, got: {msg!r}"


# ---------------------------------------------------------------------------
# KLC-034 step-1: DISCOVERY_LITE_UPGRADE_M advisory
# ---------------------------------------------------------------------------

def test_upgrade_m_signal_helper():
    assert spec_structure.has_upgrade_m_signal("DISCOVERY_LITE_UPGRADE_M")
    assert spec_structure.has_upgrade_m_signal("Emitting DISCOVERY_LITE_UPGRADE_M here.")
    assert not spec_structure.has_upgrade_m_signal("No signal here")


def test_upgrade_m_signal_recognized(tmp_path, monkeypatch):
    """DISCOVERY_LITE_UPGRADE_M in spec.md is non-blocking but surfaces a re-route advisory."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    d = _make_s_ticket(tmp_path, "KLC-U01")
    (d / "spec.md").write_text(
        _VALID_S_SPEC.format(ticket="KLC-U01") + "\nDISCOVERY_LITE_UPGRADE_M\n",
        encoding="utf-8",
    )
    (d / "options-lite.md").write_text(
        "- Option A: fast impl\n- Option B: safer impl\nPicked: Option A — lower risk\n",
        encoding="utf-8",
    )
    ok, msg = can_complete_discovery_lite("KLC-U01")
    assert ok, f"DISCOVERY_LITE_UPGRADE_M must not block ack, got: {msg!r}"
    assert "retrack" in msg, f"expected re-route advisory in msg, got: {msg!r}"


def test_socratic_impl_plan_gate_still_bites(tmp_path, monkeypatch):
    """Removing impl-plan.md from an otherwise-complete S-ticket re-blocks discovery-lite ack.

    Regression guard: the fixture repair in step-2 must not defang the gate.
    """
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _make_s_ticket(tmp_path, "KLC-BITE")
    (d / "options-lite.md").write_text(
        "- Option A: fast impl\n- Option B: safer impl\nPicked: Option A — lower risk\n",
        encoding="utf-8",
    )
    # Gate should pass with impl-plan.md present
    ok, _ = can_complete_discovery_lite("KLC-BITE")
    assert ok, "pre-condition: complete S-ticket should pass"

    # Remove the impl-plan.md — gate should bite again
    (d / "impl-plan.md").unlink()
    ok2, msg2 = can_complete_discovery_lite("KLC-BITE")
    assert not ok2, "gate must block after impl-plan.md removed"
    assert "impl-plan" in msg2.lower(), f"expected 'impl-plan' in message, got: {msg2!r}"
