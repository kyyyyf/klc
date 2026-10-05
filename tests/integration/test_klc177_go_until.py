"""KLC-177 step-3 (AC-5): `klc go <KEY> --until <phase>` over the autorunner loop.

In-process with a tmp PROJECT_ROOT (feature-off). The agent dispatch is replaced
by a stub that FAILS the test when called: `go --until` never dispatches.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (_FW, _FW / "core" / "skills", _FW / "core" / "phases"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_CLEAN = {
    "advisory": {"records": [], "threshold": "medium"},
    "scope_expansion": False, "sentinels": False, "mutation": False,
    "budget_overrun": False, "verdict": "APPROVED", "route_confidence": "high",
}
_HIGH = {**_CLEAN, "advisory": {"records": [
    {"severity": "high", "message": "spec contradicts design"}], "threshold": "medium"}}


def _flush():
    import core.skills.phases as a
    a._CACHE = None
    import phases as b
    b._CACHE = None


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_AUTORUN_CAP", raising=False)
    _flush()
    import gate_policy
    import autorunner
    import runner

    def _boom(*a, **k):
        raise AssertionError("go --until must never dispatch an agent")

    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(_CLEAN))
    monkeypatch.setattr(autorunner, "_dispatch", _boom)
    monkeypatch.setattr(runner, "run_agent", _boom)
    return tmp_path


def _ticket(root: Path, key: str, phase: str, track: str = "S") -> Path:
    td = root / ".klc" / "tickets" / key
    td.mkdir(parents=True)
    meta = {"ticket": key, "kind": "feature", "phase": phase, "track": track,
            "route_confidence": "high", "affected_modules": [], "layer": "code",
            "budgets": {"mutation_fix_attempts": 0}, "risk_tags": [],
            "phase_history": [], "rework_count": {}}
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return td


def _go(argv):
    import go
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = int(go.run(list(argv)))
    return rc, out.getvalue(), err.getvalue()


def _phase(td: Path) -> str:
    return json.loads((td / "meta.json").read_text(encoding="utf-8"))["phase"]


def test_until_stops_at_decision_high_advisory_cap_and_target_phase(proj, monkeypatch):
    # decision gate: pick required, nothing moves
    td = _ticket(proj, "U-1", "discovery:ack-needed", track="M")
    before = (td / "meta.json").read_bytes()
    rc, out, err = _go(["U-1", "--until", "build"])
    assert rc == 2, err
    assert (td / "meta.json").read_bytes() == before
    assert "--pick" in out and "\n" not in out.strip()

    # HIGH advisory at a conditional gate: stop with the advisory named
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(_HIGH))
    td = _ticket(proj, "U-2", "build:ack-needed")
    rc, out, err = _go(["U-2", "--until", "integrate"])
    assert rc == 2, err
    assert _phase(td) == "build:ack-needed"
    assert "advisory" in out and "\n" not in out.strip()
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(_CLEAN))

    # cap: one clean move, then the cap stops the loop
    td = _ticket(proj, "U-3", "build:ack-needed")
    rc, out, err = _go(["U-3", "--until", "integrate", "--cap", "1"])
    assert rc == 2, err
    assert _phase(td) == "review:work"
    assert "cap" in out and "\n" not in out.strip()

    # target phase: reaching <phase>:work is a clean stop with exit 0
    td = _ticket(proj, "U-4", "build:ack-needed")
    rc, out, err = _go(["U-4", "--until", "review"])
    assert rc == 0, err
    assert _phase(td) == "review:work"
    rc, out, err = _go(["U-4", "--until", "review"])        # already there: no move
    assert rc == 0, err
    assert _phase(td) == "review:work"


def test_until_stops_at_incomplete_work_naming_the_card(proj):
    td = _ticket(proj, "U-5", "review:work")                # review-report.md missing
    before = (td / "meta.json").read_bytes()
    rc, out, err = _go(["U-5", "--until", "integrate"])
    assert rc == 2, err
    assert (td / "meta.json").read_bytes() == before
    assert "_prompt.md" in out and "\n" not in out.strip()


def test_until_stops_at_build_that_is_not_green(proj):
    td = _ticket(proj, "U-6", "build:work")                 # no impl-plan: not green
    rc, out, err = _go(["U-6", "--until", "review"])
    assert rc == 2, err
    assert _phase(td) == "build:work"
    assert "build" in out and "\n" not in out.strip()


def test_until_never_passes_integrate_and_complete_work_is_acked_without_dispatch(proj):
    td = _ticket(proj, "U-7", "review:ack", track="M")      # observe is on the full lane only (KLC-179)
    rc, out, err = _go(["U-7", "--until", "observe"])
    assert rc == 2, err
    assert _phase(td) == "integrate:work"                   # the guardrail holds
    assert "integrate" in out

    td = _ticket(proj, "U-8", "observe:work", track="M")    # already at the target phase
    rc, out, err = _go(["U-8", "--until", "observe"])
    assert rc == 0, err
    assert _phase(td) == "observe:work"                     # `go --until` never acks the target
    rc, out, err = _go(["U-8", "--until", "integrate"])     # integrate is behind observe: refused
    assert rc == 2 and "behind" in err


def test_until_json_refusals_and_unknown_phase(proj, monkeypatch):
    _ticket(proj, "U-9", "build:ack-needed")
    rc, out, err = _go(["U-9", "--until", "review", "--json"])
    assert rc == 0, err
    data = json.loads(out)
    assert data["ticket"] == "U-9" and data["terminal"] == "until:review"

    rc, out, err = _go(["U-9", "--until", "nonsense"])
    assert rc == 2 and "nonsense" in err

    import state_feature
    monkeypatch.setattr(state_feature, "enabled", lambda: True)
    rc, out, err = _go(["U-9", "--until", "integrate"])
    assert rc == 1
    assert "multi-user" in (out + err)
