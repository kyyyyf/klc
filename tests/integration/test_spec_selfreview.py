"""Tests for core/skills/spec_selfreview.py (KLC-033 steps 1 + 2)."""
import json
import subprocess
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))  # for bare imports inside phase_completion

import core.skills.spec_selfreview as spec_selfreview  # noqa: E402
from core.skills.spec_selfreview import scan_spec  # noqa: E402
import tests.prompt_harness as prompt_harness  # noqa: E402
from core.skills.phase_completion import can_complete_discovery_lite  # noqa: E402

_SELFREVIEW_SCRIPT = _FW_ROOT / "core" / "skills" / "spec_selfreview.py"

_DIRTY_SPEC = """\
# Test spec

## Acceptance Criteria
- [ ] AC-1

[!CONFLICT C-001] unresolved
TODO: fill in
"""

_CLEAN_SPEC = """\
# Test spec

## Acceptance Criteria
- [ ] AC-1: The system does X when Y is present.
- [ ] AC-2: Error handling works correctly.
"""


def test_scan_detects_each_class():
    violations = scan_spec(_DIRTY_SPEC)
    classes = {v["class"] for v in violations}
    assert "placeholder" in classes, f"expected placeholder violation, got {violations}"
    assert "conflict" in classes, f"expected conflict violation, got {violations}"
    assert "stub_ac" in classes, f"expected stub_ac violation, got {violations}"
    assert scan_spec(_CLEAN_SPEC) == []


def test_harness_imports_canonical_tokens():
    assert prompt_harness.PLACEHOLDER_TOKENS is spec_selfreview.PLACEHOLDER_TOKENS


# ---------------------------------------------------------------------------
# Step-2: gate in phase_completion + CLI
# ---------------------------------------------------------------------------

_VALID_SPEC = """\
---
ticket: {ticket}
kind: feature
authority: agent
risk_tags: []
---

## Goals
Test goal with substance.

## Acceptance Criteria
- [ ] AC-1: The system does X when Y is present.

## Affected modules
- test_module

## Estimate
- complexity: 1
- total: 3
"""

_DIRTY_PAYLOAD = "TODO fill in the details\n"


def _make_ticket_dir(tmp_path: Path, ticket: str = "KLC-T99") -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "discovery-lite:work",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "affected_modules": ["test_module"],
        "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return ticket_dir


def test_gate_rejects_dirty_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-T99"
    ticket_dir = _make_ticket_dir(tmp_path, ticket)
    (ticket_dir / "spec.md").write_text(
        _VALID_SPEC.format(ticket=ticket) + _DIRTY_PAYLOAD, encoding="utf-8"
    )
    ok, msg = can_complete_discovery_lite(ticket)
    assert not ok, f"expected False for dirty spec, got True"
    assert "self-review" in msg, f"expected 'self-review' in message, got: {msg!r}"


def test_gate_passes_clean_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-T99"
    ticket_dir = _make_ticket_dir(tmp_path, ticket)
    (ticket_dir / "spec.md").write_text(
        _VALID_SPEC.format(ticket=ticket), encoding="utf-8"
    )
    ok, msg = can_complete_discovery_lite(ticket)
    assert ok, f"expected True for clean spec, got: {msg!r}"


def test_cli_exit_code(tmp_path):
    dirty = tmp_path / "dirty.md"
    dirty.write_text("TODO something\n", encoding="utf-8")
    clean = tmp_path / "clean.md"
    clean.write_text("No violations here.\n", encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(_SELFREVIEW_SCRIPT), "--file", str(dirty)],
        capture_output=True, text=True, cwd=str(_FW_ROOT),
    )
    assert r.returncode == 1, f"expected exit 1 for dirty file, got {r.returncode}"
    data = json.loads(r.stdout)
    assert data["violations"]

    r = subprocess.run(
        [sys.executable, str(_SELFREVIEW_SCRIPT), "--file", str(clean)],
        capture_output=True, text=True, cwd=str(_FW_ROOT),
    )
    assert r.returncode == 0, f"expected exit 0 for clean file, got {r.returncode}"
    data = json.loads(r.stdout)
    assert data["violations"] == []
