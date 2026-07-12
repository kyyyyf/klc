"""KLC-052 step-8/AC-11: discovery is modeled as clarify (main-loop,
interactive) + author (background subagent, synthesis) — a behavior of
the loop + the clarify_required stamp, not a phases.yml reshape. No
new discovery phase id is introduced.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))


def _write_meta(tmp_path: Path, ticket: str, meta: dict) -> None:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True, exist_ok=True)
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_discovery_split_clarify_then_author(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.skills import phase_resolver as pr
    from core.skills import phases as ph_mod
    ph_mod._CACHE = None

    ticket = "KLC-9401"

    # Stage 1 — gate not yet cleared: the loop must stop at `intake`,
    # never reaching the discovery author subagent.
    _write_meta(tmp_path, ticket, {
        "ticket": ticket, "track": "M", "phase": "intake:work",
        "clarify_required": True,
    })
    gate = pr.resolve_phase(ticket, "intake")
    assert gate.interactive is True

    # Stage 2 — gate cleared (main loop ran the clarify pass, wrote
    # answers back, re-routed, cleared the stamp): the SAME ticket,
    # now at `discovery`, resolves to the ordinary `klc-discovery`
    # author subagent — no new phases.yml id, no interactive flag.
    _write_meta(tmp_path, ticket, {
        "ticket": ticket, "track": "M", "phase": "discovery:work",
        "clarify_required": False,
    })
    author = pr.resolve_phase(ticket, "discovery")
    assert author.interactive is False
    assert author.runs_inline is False
    assert author.agent_type == "klc-discovery"
