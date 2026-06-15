"""KLC-028 step-3: can_complete_discovery rejects unjustified downgrades."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core" / "skills"))
from phase_completion import can_complete_discovery


def _write_spec(ticket_dir: Path, ticket: str) -> None:
    spec = ticket_dir / "spec.md"
    spec.write_text(
        f"---\nticket: {ticket}\nkind: feature\nauthority: agent\n---\n\n"
        "## Goals\nTest.\n\n## Acceptance Criteria\n- AC-1: pass.\n\n"
        "## Estimate\ncomplexity: 1\n",
        encoding="utf-8",
    )


def _write_meta(ticket_dir: Path, ticket: str, track: str, route_hint: str,
                estimate: dict, affected_modules: list) -> None:
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "discovery:work",
        "track": track,
        "route_hint": route_hint,
        "estimate": estimate,
        "affected_modules": affected_modules,
        "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_modules(index_dir: Path, modules: list) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "modules.json").write_text(
        json.dumps({"modules": modules}), encoding="utf-8"
    )


def _estimate(complexity=1, uncertainty=1, risk=1, manual=0, total=None):
    t = total if total is not None else complexity + uncertainty + risk + manual
    return {"complexity": complexity, "uncertainty": uncertainty,
            "risk": risk, "manual": manual, "total": t}


# ---------------------------------------------------------------------------

def test_unjustified_downgrade_rejected(tmp_path, monkeypatch):
    """track < route_hint with no blast-radius evidence → rejected."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-T01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    index_dir = tmp_path / ".klc" / "index"

    _write_spec(ticket_dir, ticket)
    _write_meta(ticket_dir, ticket, track="S", route_hint="M",
                estimate=_estimate(1, 1, 1, 0, total=3),
                affected_modules=["modA"])
    # modA has no depended_by → downgrade not safe
    _write_modules(index_dir, [{"name": "modA", "path": "src/a", "depends_on": []}])

    ok, msg = can_complete_discovery(ticket)
    assert not ok
    assert "floor" in msg.lower() or "below" in msg.lower() or "blast" in msg.lower()


def test_justified_downgrade_accepted(tmp_path, monkeypatch):
    """track < route_hint but zero external dependents → accepted."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-T02"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    index_dir = tmp_path / ".klc" / "index"

    _write_spec(ticket_dir, ticket)
    _write_meta(ticket_dir, ticket, track="S", route_hint="M",
                estimate=_estimate(1, 1, 1, 0, total=3),
                affected_modules=["modA"])
    # modA has depended_by=[] → zero external dependents → safe
    _write_modules(index_dir, [{"name": "modA", "path": "src/a",
                                "depends_on": [], "depended_by": []}])

    ok, msg = can_complete_discovery(ticket)
    assert ok, f"Expected ok but got: {msg}"


def test_no_downgrade_unaffected(tmp_path, monkeypatch):
    """track == route_hint → guard is a no-op."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-T03"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    index_dir = tmp_path / ".klc" / "index"

    _write_spec(ticket_dir, ticket)
    _write_meta(ticket_dir, ticket, track="M", route_hint="M",
                estimate=_estimate(2, 2, 1, 1, total=6),
                affected_modules=["modA"])
    _write_modules(index_dir, [{"name": "modA", "path": "src/a", "depends_on": []}])

    ok, msg = can_complete_discovery(ticket)
    assert ok, f"Expected ok (no downgrade) but got: {msg}"
