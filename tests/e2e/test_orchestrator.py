"""KLC-052 step-7: the orchestrator's step 1+3 (design.md §3) — resolve
the current phase via `klc status --json`, then feed it straight into
`phase_resolver.resolve_phase` with no re-derivation in between.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))


def _make_ticket(tmp_path: Path, ticket: str, track: str, phase: str) -> None:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True, exist_ok=True)
    meta = {"ticket": ticket, "track": track, "kind": "tech", "phase": phase}
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_run_skill_resolves_phase_via_klc_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_ticket(tmp_path, "KLC-9301", "M", "design:work")

    import status as status_mod
    rc = status_mod.run(["KLC-9301", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["phase_id"] == "design"
    assert out["track"] == "M"

    from core.skills import phase_resolver as pr
    resolved = pr.resolve_phase("KLC-9301", out["phase_id"])
    assert resolved.track == out["track"]
    assert resolved.runs_inline is False  # M-track, not XS fast-track
    assert resolved.agent_type == "klc-design"
