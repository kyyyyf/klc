#!/usr/bin/env python3
"""Integration: the KLC-083 spec-quality marker gate wired into phase_completion.

An open [NEEDS CLARIFICATION] marker must block discovery / discovery-lite
completion (it must not silently pass); removing it lets the same spec pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.phase_completion import (  # noqa: E402
    can_complete_discovery,
    can_complete_discovery_lite,
)

_S_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
risk_tags: []
---

## Goals
Provide a concrete implementation for the required feature.

## Acceptance Criteria
- [ ] AC-1: the gate · blocks · discovery ack · when an open clarification remains
{marker}
## Affected
test_module: core/test.py, src=core/test.py:1

## Estimate
complexity: 1
uncertainty: 1
risk: 1
manual: 0
total: 3
"""

_OPTIONS = "- Option A: fast impl\n- Option B: safer impl\nPicked: Option A — lower risk\n"

_IMPL_PLAN = """\
## step-1 — do the thing

- **Goal:** implement the feature
- RED: not applicable
- **Interfaces:** `def f() -> None`
- **Expected:** f runs
- **VERIFY:** pytest
- **COMMIT:** KLC-X step-1: do the thing
- **Affected:** src/x.py
"""


def _make_s_ticket(tmp_path: Path, ticket: str, marker: str) -> Path:
    d = tmp_path / ".klc" / "tickets" / ticket
    d.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery-lite:work",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "affected_modules": ["test_module"], "layer": "code",
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "spec.md").write_text(_S_SPEC.format(ticket=ticket, marker=marker), encoding="utf-8")
    (d / "options-lite.md").write_text(_OPTIONS, encoding="utf-8")
    (d / "impl-plan.md").write_text(_IMPL_PLAN, encoding="utf-8")
    return d


def test_open_marker_blocks_discovery_lite(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_s_ticket(tmp_path, "KLC-Q01", "[NEEDS CLARIFICATION: which floor applies?]\n")
    ok, msg = can_complete_discovery_lite("KLC-Q01")
    assert not ok
    assert "NEEDS CLARIFICATION" in msg


def test_resolved_spec_passes_discovery_lite(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_s_ticket(tmp_path, "KLC-Q02", "")  # no marker
    ok, msg = can_complete_discovery_lite("KLC-Q02")
    assert ok, f"expected pass with no open marker, got: {msg!r}"


def test_operator_can_defer_marker(tmp_path, monkeypatch):
    # Sanctioned escape hatch (mirrors KLC-027 retrack): meta.deferred_markers
    # lets an operator ack past a KNOWINGLY-deferred marker; it is then surfaced
    # as a warning, not silenced, and not a hard block.
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _make_s_ticket(tmp_path, "KLC-Q04", "[NEEDS CLARIFICATION: deferred on purpose]\n")
    meta = json.loads((d / "meta.json").read_text())
    meta["deferred_markers"] = True
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    ok, msg = can_complete_discovery_lite("KLC-Q04")
    assert ok, f"expected deferred-marker ack to pass, got: {msg!r}"
    assert "deferred" in msg


_M_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: human
risk_tags: []
---

## Goals
Ship the spec-quality gate.

## Acceptance Criteria
- [ ] AC-1: the gate · blocks · discovery ack · when an open clarification remains
{marker}
## Affected modules
- test_module: core/test.py

## Estimate
complexity: 2
uncertainty: 1
risk: 1
manual: 0
total: 4

- Option A: fast impl
- Option B: safer impl

Picked: Option A — lower risk
"""


def _make_m_ticket(tmp_path: Path, ticket: str, marker: str) -> Path:
    d = tmp_path / ".klc" / "tickets" / ticket
    d.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery:work",
        "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "affected_modules": ["test_module"], "layer": "code",
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "spec.md").write_text(_M_SPEC.format(ticket=ticket, marker=marker), encoding="utf-8")
    return d


def test_open_marker_blocks_discovery_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_m_ticket(tmp_path, "KLC-Q03", "\n[NEEDS CLARIFICATION: which floor applies?]\n")
    ok, msg = can_complete_discovery("KLC-Q03")
    assert not ok
    assert "NEEDS CLARIFICATION" in msg
