"""KLC-176 step-1 (AC-1, AC-2): approaches and the pick live in spec.md `## Approaches`."""
import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills import spec_structure  # noqa: E402
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
- [ ] AC-1: The gate passes when spec.md carries two approaches and a pick.

{approaches}
## Affected
test_module: core/test.py, src=core/test.py:1

## Estimate
complexity: 1
uncertainty: 1
risk: 1
manual: 0
total: 3
"""

_M_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
---

## Goals
Provide a concrete implementation for the required M-track feature.

## Acceptance Criteria
- [ ] AC-1: The system does X when Y is present.

{approaches}
## Estimate
complexity: 2
uncertainty: 1
risk: 1
manual: 0
total: 4
"""

_TWO = """\
## Approaches
- Option A: fast impl — quick but narrow
- Option B: safer impl — slower but robust

Picked: Option A — lower risk
"""

_ONE = """\
## Approaches
- Option A: fast impl — quick but narrow

Picked: Option A — lower risk
"""

_PLAN = """\
## step-1 — do the thing

- **Goal:** implement the feature
- RED: not applicable
- **Interfaces:** `def f() -> None`
- **Expected:** f runs
- **VERIFY:** pytest
- **COMMIT:** KLC-X step-1: do the thing
- **Affected:** src/x.py
"""


def _ticket(tmp_path, key, track, spec):
    d = tmp_path / ".klc" / "tickets" / key
    d.mkdir(parents=True)
    est = ({"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3}
           if track == "S" else
           {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4})
    meta = {"ticket": key, "kind": "feature", "track": track, "route_hint": track,
            "phase": "discovery:work", "estimate": est,
            "affected_modules": ["test_module"], "layer": "code"}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "spec.md").write_text(spec, encoding="utf-8")
    if track == "S":
        (d / "impl-plan.md").write_text(_PLAN, encoding="utf-8")
    return d


def test_approaches_text_extracts_section_and_ignores_fences():
    body = spec_structure.approaches_text("## Goals\nx\n\n## Approaches\n- Option A: a\n\n## Estimate\ny\n")
    assert body is not None and "Option A" in body and "Estimate" not in body
    fenced = "## Goals\nx\n\n```\n## Approaches\n- Option A: a\n- Option B: b\nPicked: A\n```\n"
    assert spec_structure.approaches_text(fenced) is None
    assert spec_structure.approaches_text("## Goals\nx\n") is None


def test_s_ack_passes_with_approaches_section_and_no_options_lite(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _ticket(tmp_path, "KLC-A01", "S", _S_SPEC.format(ticket="KLC-A01", approaches=_TWO))
    assert not (d / "options-lite.md").exists()
    ok, msg = can_complete_discovery_lite("KLC-A01")
    assert ok, msg


def test_s_ack_blocked_without_section_or_with_one_option(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-A02", "S", _S_SPEC.format(ticket="KLC-A02", approaches=""))
    ok, msg = can_complete_discovery_lite("KLC-A02")
    assert not ok and "approaches" in msg.lower()
    _ticket(tmp_path, "KLC-A03", "S", _S_SPEC.format(ticket="KLC-A03", approaches=_ONE))
    ok, msg = can_complete_discovery_lite("KLC-A03")
    assert not ok and "approach" in msg.lower()
    nopick = "## Approaches\n- Option A: a\n- Option B: b\n"
    _ticket(tmp_path, "KLC-A04", "S", _S_SPEC.format(ticket="KLC-A04", approaches=nopick))
    ok, msg = can_complete_discovery_lite("KLC-A04")
    assert not ok and "pick" in msg.lower()


def test_s_ack_blocked_when_spec_unreadable(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _ticket(tmp_path, "KLC-A05", "S", "x")
    (d / "spec.md").unlink()
    ok, msg = can_complete_discovery_lite("KLC-A05")
    assert not ok


def test_section_beats_legacy_options_lite(tmp_path, monkeypatch):
    """A present-but-thin section is not rescued by a stale options-lite.md."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _ticket(tmp_path, "KLC-A06", "S", _S_SPEC.format(ticket="KLC-A06", approaches=_ONE))
    (d / "options-lite.md").write_text(
        "- Option A: a\n- Option B: b\nPicked: Option A — r\n", encoding="utf-8")
    ok, _ = can_complete_discovery_lite("KLC-A06")
    assert not ok


def test_legacy_options_lite_still_satisfies_s_check(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _ticket(tmp_path, "KLC-A07", "S", _S_SPEC.format(ticket="KLC-A07", approaches=""))
    (d / "options-lite.md").write_text(
        "- Option A: a\n- Option B: b\nPicked: Option A — r\n", encoding="utf-8")
    ok, msg = can_complete_discovery_lite("KLC-A07")
    assert ok, msg


def test_discovery_blocks_without_approaches_section(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-A08", "M", _M_SPEC.format(ticket="KLC-A08", approaches=""))
    ok, msg = can_complete_discovery("KLC-A08")
    assert not ok and "approaches" in msg.lower()
    # approaches written loose in the body (no section) no longer count
    loose = "- Option A: a\n- Option B: b\nPicked: Option A — r\n"
    _ticket(tmp_path, "KLC-A09", "M", _M_SPEC.format(ticket="KLC-A09", approaches=loose))
    ok, msg = can_complete_discovery("KLC-A09")
    assert not ok


def test_discovery_passes_with_section(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-A10", "M", _M_SPEC.format(ticket="KLC-A10", approaches=_TWO))
    ok, msg = can_complete_discovery("KLC-A10")
    assert ok, msg
    _ticket(tmp_path, "KLC-A11", "M", _M_SPEC.format(ticket="KLC-A11", approaches=_ONE))
    ok, msg = can_complete_discovery("KLC-A11")
    assert not ok and "approach" in msg.lower()
