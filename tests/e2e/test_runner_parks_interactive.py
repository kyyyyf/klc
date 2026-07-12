"""KLC-052 step-3: runner.py consumes phase_resolver and parks (never
dispatches) on interactive phases — enforcing C-005.

Fail-closed test: interactive input must be refused by the headless
runner path, not silently executed by a provider dispatcher.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))


def _make_ticket(tmp_path: Path, ticket: str, track: str, **extra_meta) -> None:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True, exist_ok=True)
    meta = {"ticket": ticket, "track": track, "phase": "placeholder:work", **extra_meta}
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_runner_parks_on_interactive_phase(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import runner

    dispatched = {"called": False}

    def _fake_dispatcher(*args, **kwargs):
        dispatched["called"] = True
        return 0, "should not run", ""

    monkeypatch.setitem(runner._DISPATCH, "anthropic", _fake_dispatcher)

    _make_ticket(tmp_path, "KLC-PARK01", "M", clarify_required=True)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("do the thing", encoding="utf-8")
    out_path = tmp_path / "out.md"

    rc = runner.run_agent(
        phase_id="intake",
        prompt_path=prompt_path,
        out_path=out_path,
        track="M",
        ticket="KLC-PARK01",
    )

    assert rc != 0
    assert dispatched["called"] is False

    meta = json.loads((tmp_path / ".klc" / "tickets" / "KLC-PARK01" / "meta.json").read_text())
    parked = meta.get("parked")
    out_text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    assert parked is not None or "[!PARKED]" in out_text
