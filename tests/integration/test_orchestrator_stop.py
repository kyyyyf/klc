"""KLC-052 step-7: orchestrator stop conditions (AC-5) — non-empty
blocking_questions and the interactive clarify gate both halt the loop.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import run_signal  # noqa: E402


def _make_ticket(tmp_path: Path, ticket: str, track: str, **extra_meta) -> None:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True, exist_ok=True)
    meta = {"ticket": ticket, "track": track, "phase": "placeholder:work", **extra_meta}
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_stops_when_blocking_questions_nonempty():
    text = (
        '```json\n{"phase":"discovery","signal":"blocked","artifacts":[],'
        '"blocking_questions":["which auth provider?"],"next_action":"clarify"}\n```\n'
    )
    sig = run_signal.parse_signal(text, expected_phase="discovery")
    assert sig is not None
    # AC-5(c): non-empty blocking_questions is a stop condition.
    assert bool(sig.blocking_questions) is True


def test_stops_at_interactive_clarify_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.skills import phase_resolver as pr

    _make_ticket(tmp_path, "KLC-9101", "M", clarify_required=True)
    resolved = pr.resolve_phase("KLC-9101", "intake")
    # AC-5(a): resolved.interactive == True is a stop condition — the
    # loop must never dispatch past it.
    assert resolved.interactive is True
