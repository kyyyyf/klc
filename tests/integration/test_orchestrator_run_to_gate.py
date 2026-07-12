"""KLC-052 step-7: after a clean "done" signal, the orchestrator's
`klc ack --auto` + `klc next` throttle (AC-4, reusing KLC-045
gate-policy) actually advances the ticket to the next phase's work
state — the seam the SKILL.md loop's step 6 relies on.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import run_signal  # noqa: E402


def _flush_phases_cache():
    import core.skills.phases as ph_mod
    ph_mod._CACHE = None


def _make_build_ticket(tmp_path: Path, ticket: str) -> Path:
    """Ticket in build:ack-needed — single conditional forward pick
    (mirrors tests/integration/test_gate_policy.py's fixture)."""
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "build:ack-needed",
        "track": "S",
        "route_confidence": "high",
        "affected_modules": ["test_module"],
        "layer": "code",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "budgets": {"mutation_fix_attempts": 0},
        "phase_history": [],
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(
        "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
        "## Affected\ntest_module: core/test.py, src=core/test.py:1\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
        .format(t=ticket),
        encoding="utf-8",
    )
    (td / "impl-plan.md").write_text(
        "## step-1 — do the thing\n- **Goal:** implement\n- RED: not applicable\n"
        "- **Interfaces:** `def f() -> None`\n- **Expected:** f runs\n"
        "- **VERIFY:** pytest\n- **COMMIT:** KLC-X step-1: do the thing\n"
        "- **Affected:** src/x.py\n- **Code sketch:**\n```python\npass\n```\n",
        encoding="utf-8",
    )
    (td / "build-log.md").write_text(
        "## Evidence\n\n```\n$ pytest\n1 passed\n```\n", encoding="utf-8",
    )
    return td


_CLEAN_SIG = {
    "advisory": "",
    "scope_expansion": False,
    "sentinels": False,
    "mutation": False,
    "budget_overrun": False,
    "verdict": "APPROVED",
    "route_confidence": "high",
}


def test_ack_auto_then_next_after_done(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    ticket = "KLC-9201"
    _make_build_ticket(tmp_path, ticket)

    # A clean "done" signal from the build phase agent.
    text = (
        '```json\n{"phase":"build","signal":"done","artifacts":["build-log.md"],'
        '"blocking_questions":[],"next_action":"ack"}\n```\n'
    )
    sig = run_signal.parse_signal(text, expected_phase="build")
    assert sig is not None
    assert sig.next_action == "ack"
    assert not sig.blocking_questions  # AC-5(c) does not fire — loop proceeds

    import ack as ack_mod
    monkeypatch.setattr(ack_mod._gp, "collect_signals", lambda t, p: dict(_CLEAN_SIG))

    rc = ack_mod.run([ticket, "--auto"])
    assert rc == 0

    from core.skills import lifecycle
    assert lifecycle.current_state(ticket) == "review:work"
