#!/usr/bin/env python3
"""KLC-116 step-4 — AC-7..AC-10, AC-16, AC-17: the design-acceptance gate.

Blocks an unmeasured load-bearing decision on M/L, surfaces the same list on
S, skips entirely on XS, and lets an operator override by exact item id.
Revision-2 additions (D-205/D-206): the block message labels each offender
with its channel and the override count; the ASSUMPTION exemption is narrowed
to the document channel only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import provenance  # noqa: E402

sys.path.insert(0, str(FW_ROOT))
from core.skills.phase_completion import (  # noqa: E402
    can_complete, can_complete_discovery_lite,
)

FIXTURES = FW_ROOT / "tests" / "fixtures" / "klc116"


def _seed(tmp_path: Path, ticket: str, files: dict[str, str],
          *, deferred_provenance: list[str] | None = None) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:work",
        "phase_history": [], "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
        "affected_modules": ["core/skills"], "created": "2026-01-01T00:00:00Z",
    }
    if deferred_provenance is not None:
        meta["deferred_provenance"] = deferred_provenance
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for rel, body in files.items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tdir


_ASSUMED_OPTIONS = (
    "## Option A — do X (recommended: true)\n\n"
    "> [!DECISION D-1] evidence=assumed if-false=revisit\n"
    "> the page scrolls, and five mechanisms are built on that\n"
)

_NO_ATTR_OPTIONS = (
    "## Option A — do X (recommended: true)\n\n"
    "> [!DECISION D-1] owner=ek\n"
    "> the page scrolls, and five mechanisms are built on that\n"
)


def test_m_track_blocks_on_assumed_load_bearing_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-940"
    _seed(tmp_path, ticket, {"design/options.md": _ASSUMED_OPTIONS})
    block, warns = provenance.design_gate(ticket, "M")
    assert "D-1" in block
    assert "design/options.md" in block


def test_m_track_blocks_on_load_bearing_decision_with_no_evidence_attribute(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-941"
    _seed(tmp_path, ticket, {"design/options.md": _NO_ATTR_OPTIONS})
    block, warns = provenance.design_gate(ticket, "M")
    assert "D-1" in block
    assert "no evidence attribute" in block


def test_l_track_blocks_same_rule_as_m_track(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-942"
    _seed(tmp_path, ticket, {"design/options.md": _ASSUMED_OPTIONS})
    block, warns = provenance.design_gate(ticket, "L")
    assert "D-1" in block


def test_s_track_surfaces_advisory_and_phase_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-943"
    _seed(tmp_path, ticket, {"design/options.md": _ASSUMED_OPTIONS})
    block, warns = provenance.design_gate(ticket, "S")
    assert block == ""
    assert any("D-1" in w and "load-bearing" in w for w in warns)


def test_xs_track_skips_provenance_check_entirely(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-944"
    _seed(tmp_path, ticket, {"design/options.md": _ASSUMED_OPTIONS})
    assert provenance.design_gate(ticket, "XS") == ("", [])


def test_override_naming_offending_id_passes_with_advisory_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-945"
    _seed(tmp_path, ticket, {"design/options.md": _ASSUMED_OPTIONS},
          deferred_provenance=["D-1"])
    block, warns = provenance.design_gate(ticket, "M")
    assert block == ""
    assert any("D-1" in w and "excused" in w for w in warns)
    assert any("1 of 1" in w for w in warns)


def test_override_naming_different_id_still_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-946"
    _seed(tmp_path, ticket, {"design/options.md": _ASSUMED_OPTIONS},
          deferred_provenance=["D-999"])
    block, warns = provenance.design_gate(ticket, "M")
    assert "D-1" in block
    assert any("D-999" in w and "unknown" in w for w in warns)


def test_fixture_with_assumed_load_bearing_decision_fails_m_track_named(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-947"
    _seed(tmp_path, ticket, {
        "design/options.md": (FIXTURES / "options-assumed.md").read_text(encoding="utf-8"),
    })
    block, warns = provenance.design_gate(ticket, "M")
    assert "D-901" in block


def test_same_fixture_rewritten_observed_passes_m_track(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-948"
    _seed(tmp_path, ticket, {
        "design/options.md": (FIXTURES / "options-observed.md").read_text(encoding="utf-8"),
    })
    block, warns = provenance.design_gate(ticket, "M")
    assert block == ""


def test_document_channel_assumption_surfaces_and_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-949"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\n"
            "## Decisions\n\n"
            "> [!ASSUMPTION A-1] evidence=assumed if-false=revisit\n"
            "> a guess, load-bearing only through the document channel\n"
        )
    })
    block, warns = provenance.design_gate(ticket, "M")
    assert block == ""
    assert any("A-1" in w and "ASSUMPTION" in w for w in warns)


def test_step_premise_assumption_blocks_on_m_track(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-950"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\n"
            "## Decisions\n\n"
            "> [!ASSUMPTION A-1] evidence=assumed if-false=revisit\n"
            "> a guess a later build step literally depends on\n"
        ),
        "impl-plan.md": (
            "## step-1 — build the thing\n\n"
            "- Depends on: A-1\n"
        ),
    })
    block, warns = provenance.design_gate(ticket, "M")
    assert "A-1" in block
    assert "[step-premise]" in block


def test_block_message_labels_each_offender_with_its_channel_and_counts_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-951"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "## Option A — do X (recommended: true)\n\n"
            "> [!DECISION D-1] evidence=assumed if-false=x\n"
            "> a document-level offender, excused by override\n\n"
            "> [!ASSUMPTION D-3] evidence=assumed if-false=y\n"
            "> a step-premise offender, not excused\n"
        ),
        "impl-plan.md": (
            "## step-1 — build the thing\n\n"
            "- Depends on: D-3\n"
        ),
    }, deferred_provenance=["D-1"])
    block, warns = provenance.design_gate(ticket, "M")
    # D-1 is excused (never listed among the block's offenders); D-3 is the
    # one surviving offender, and it is labelled with its channel.
    assert "D-1" not in block
    assert "[step-premise] D-3" in block
    assert any("D-1" in w and "excused" in w for w in warns)
    assert any("1 of 2" in w for w in warns)


# --- review-fix (MEDIUM, AC-7..AC-10): drive the gate through its REAL call
# sites — phase_completion.can_complete(ticket, "design") for the M/L block,
# and can_complete_discovery_lite(ticket) for the S surface — instead of only
# ever calling provenance.design_gate() directly. Mirrors
# tests/integration/test_plan_completeness_gate.py's fixture pattern for the
# impl-plan-completeness gate this one sits next to. --------------------------

_CLEAN_IMPL_PLAN_WIRING = """\
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


def _make_m_ticket_for_wiring(tmp_path: Path, ticket: str, *,
                              options_md: str,
                              deferred_provenance: list[str] | None = None) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "design:ack-needed",
        "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "affected_modules": ["phase_completion"], "layer": "code",
    }
    if deferred_provenance is not None:
        meta["deferred_provenance"] = deferred_provenance
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "design").mkdir()
    (ticket_dir / "design" / "options.md").write_text(options_md, encoding="utf-8")
    (ticket_dir / "impl-plan.md").write_text(
        _CLEAN_IMPL_PLAN_WIRING.format(ticket=ticket), encoding="utf-8")
    return ticket_dir


def test_design_ack_via_can_complete_blocks_on_unmeasured_load_bearing_decision(
        tmp_path, monkeypatch):
    """AC-7: the REAL M-track design ack (phase_completion.can_complete) blocks
    on an unmeasured load-bearing decision — not just provenance.design_gate()
    called in isolation."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-960"
    _make_m_ticket_for_wiring(tmp_path, ticket, options_md=_ASSUMED_OPTIONS)

    ok, msg = can_complete(ticket, "design")
    assert not ok
    assert "design:" in msg
    assert "D-1" in msg


def test_design_ack_via_can_complete_persists_override_record(tmp_path, monkeypatch):
    """AC-10: an operator override (meta.deferred_provenance) lets the REAL
    design ack proceed, and persists a provenance[override] record into
    design/ack-advisories.json — the same artifact gate_policy reads."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-961"
    _make_m_ticket_for_wiring(tmp_path, ticket, options_md=_ASSUMED_OPTIONS,
                              deferred_provenance=["D-1"])

    ok, msg = can_complete(ticket, "design", persist=True)
    assert ok, f"expected the override to let the ack proceed, got: {msg!r}"

    advisories_path = (tmp_path / ".klc" / "tickets" / ticket / "design"
                       / "ack-advisories.json")
    assert advisories_path.exists()
    envelope = json.loads(advisories_path.read_text(encoding="utf-8"))
    records = [r for r in envelope["records"] if r["source"] == "provenance"]
    assert any("provenance[override]" in r["message"] and "D-1" in r["message"]
              for r in records)
    assert any("provenance[override:count]" in r["message"] for r in records)


def _make_s_ticket_for_wiring(tmp_path: Path, ticket: str, *, options_md: str) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery-lite:ack-needed",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "affected_modules": ["phase_completion"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    spec = (
        "---\n"
        f"ticket: {ticket}\n"
        "kind: feature\n"
        "risk_tags: []\n"
        "---\n\n"
        "## Goals\nDo the thing.\n\n"
        "## Acceptance Criteria\n- [ ] AC-1: it works.\n\n"
        "## Affected\nphase_completion: core/skills/phase_completion.py\n\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
    )
    (ticket_dir / "spec.md").write_text(spec, encoding="utf-8")
    (ticket_dir / "options-lite.md").write_text(
        "- Option A: inline\n- Option B: hook\nPicked: Option A\n", encoding="utf-8")
    (ticket_dir / "impl-plan.md").write_text(
        _CLEAN_IMPL_PLAN_WIRING.format(ticket=ticket), encoding="utf-8")
    (ticket_dir / "design").mkdir()
    (ticket_dir / "design" / "options.md").write_text(options_md, encoding="utf-8")
    return ticket_dir


def test_discovery_lite_ack_via_can_complete_surfaces_without_blocking(tmp_path, monkeypatch):
    """AC-8: the REAL S-track discovery-lite ack
    (phase_completion.can_complete_discovery_lite) surfaces the same
    load-bearing offender as an advisory, but the ack still succeeds."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-962"
    _make_s_ticket_for_wiring(tmp_path, ticket, options_md=_ASSUMED_OPTIONS)

    ok, msg = can_complete_discovery_lite(ticket, persist=True)
    assert ok, f"expected S-track to surface, never block, got: {msg!r}"

    advisories_path = (tmp_path / ".klc" / "tickets" / ticket / "discovery-lite"
                       / "ack-advisories.json")
    assert advisories_path.exists()
    envelope = json.loads(advisories_path.read_text(encoding="utf-8"))
    records = [r for r in envelope["records"] if r["source"] == "provenance"]
    assert any("D-1" in r["message"] for r in records)
