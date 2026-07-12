"""KLC-052 step-1: phase_resolver.resolve_phase as the single phase→agent
source of truth for the orchestrator.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))


def _make_ticket(tmp_path: Path, ticket: str, track: str) -> None:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True, exist_ok=True)
    meta = {"ticket": ticket, "track": track, "phase": "placeholder:work"}
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_dispatch_decision_derives_from_meta_and_phases_yml(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.skills import phase_resolver as pr

    _make_ticket(tmp_path, "KLC-XS01", "XS")
    resolved_xs = pr.resolve_phase("KLC-XS01", "xs-build")
    assert resolved_xs.runs_inline is True

    _make_ticket(tmp_path, "KLC-M01", "M")
    resolved_m = pr.resolve_phase("KLC-M01", "design")
    assert resolved_m.runs_inline is False
    assert resolved_m.agent_type == "klc-design"


# ---------------------------------------------------------------------------
# Regression (fresh-review finding, post-step-7): agent_type must derive from
# phase.prompt's filename stem, not phase_id — several phases share one
# agent file (build -> impl.md, manual -> manual-check.md, learn ->
# retrospective.md, acceptance-test-plan/detailed-test-plan -> test-planner.md).
# The bug returned agent_type=None for all of these, silently breaking
# Task-tool dispatch (AC-2) for the majority of non-XS phase executions.
# ---------------------------------------------------------------------------

_EXPECTED_AGENT_BY_PHASE = {
    "discovery-lite":       "klc-discovery-lite",
    "discovery":            "klc-discovery",
    "acceptance-test-plan": "klc-test-planner",
    "design":               "klc-design",
    "detailed-test-plan":   "klc-test-planner",
    "build":                "klc-impl",
    "review-lite":          "klc-review-lite",
    "review":               "klc-review",
    "manual":               "klc-manual-check",
    "learn":                "klc-retrospective",
}

# Phases with an empty prompt in phases.yml — no dispatch agent at all.
_NO_AGENT_PHASES = {"intake", "integrate", "observe"}


def test_agent_type_derives_from_prompt_stem_not_phase_id(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.skills import phase_resolver as pr
    from core.skills import phases as ph_mod

    for phase_id, expected_agent in _EXPECTED_AGENT_BY_PHASE.items():
        phase = ph_mod.load_phases().by_id(phase_id)
        track = phase.tracks[-1]  # a track this phase actually runs on
        ticket = f"KLC-AGT-{phase_id}"
        _make_ticket(tmp_path, ticket, track)
        resolved = pr.resolve_phase(ticket, phase_id)
        assert resolved.agent_type == expected_agent, (
            f"phase {phase_id!r} on track {track!r}: expected agent_type "
            f"{expected_agent!r}, got {resolved.agent_type!r}"
        )


def test_no_agent_phases_resolve_to_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.skills import phase_resolver as pr
    from core.skills import phases as ph_mod

    for phase_id in _NO_AGENT_PHASES:
        phase = ph_mod.load_phases().by_id(phase_id)
        track = phase.tracks[-1]
        ticket = f"KLC-NOAGT-{phase_id}"
        _make_ticket(tmp_path, ticket, track)
        resolved = pr.resolve_phase(ticket, phase_id)
        assert resolved.agent_type is None, (
            f"phase {phase_id!r} should have no dispatch agent, got {resolved.agent_type!r}"
        )
