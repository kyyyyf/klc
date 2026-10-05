"""KLC-180 step-4 — AC-8: the subagent is dispatched with an explicit `model=`
taken from models.yml for the ticket's TRACK (per_track honoured)."""
from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parents[2]
for _p in (FW, FW / "core" / "skills", FW / "core" / "phases"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_CLEAN = {
    "advisory": {"records": [], "threshold": "medium"},
    "scope_expansion": False, "sentinels": False, "mutation": False,
    "budget_overrun": False, "verdict": "APPROVED", "route_confidence": "high",
}


def _flush():
    import core.skills.phases as a
    a._CACHE = None
    import phases as b
    b._CACHE = None
    import models
    models._CACHE = None


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """Scratch project: models.yml override where XS reviews with the cheap role."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    cfg = tmp_path / ".klc" / "config"
    cfg.mkdir(parents=True)
    base = (FW / "config" / "models.yml").read_text(encoding="utf-8")
    base = base.split("\nper_track:")[0]
    (cfg / "models.yml").write_text(
        base + "\nper_track:\n  XS:\n    review: local-simple\n", encoding="utf-8")
    _flush()
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(_CLEAN))
    yield tmp_path
    _flush()


def _ticket(root: Path, key: str, phase: str, track: str) -> Path:
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


def test_dispatch_spec_honours_per_track_model(proj):
    import dispatch_spec as ds
    _ticket(proj, "D-XS", "review:work", "XS")
    _ticket(proj, "D-M", "review:work", "M")
    xs = ds.dispatch_spec("D-XS", "review")
    m = ds.dispatch_spec("D-M", "review")
    assert xs["model"] == "haiku"
    assert m["model"] == "sonnet"
    assert xs["model"] != m["model"]
    assert xs["agent_type"] == m["agent_type"] == "klc-review"
    assert xs["card"].endswith(".md") and "D-XS" in xs["card"]


def test_dispatch_spec_has_no_agent_for_phase_without_prompt(proj):
    import dispatch_spec as ds
    _ticket(proj, "D-I", "integrate:work", "M")
    assert ds.dispatch_spec("D-I", "integrate") is None


def test_dispatch_spec_cli_prints_json(proj):
    import subprocess
    _ticket(proj, "D-C", "review:work", "XS")
    import os
    env = dict(os.environ, PROJECT_ROOT=str(proj))
    r = subprocess.run([sys.executable, str(FW / "core" / "skills" / "dispatch_spec.py"),
                        "D-C", "review"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["model"] == "haiku"


def test_go_stop_line_carries_the_dispatch_line(proj):
    _ticket(proj, "D-G", "review:work", "XS")
    rc, out, err = _go(["D-G", "--until", "integrate"])
    assert rc == 2, err
    m = re.search(r"dispatch: agent=(klc-[\w-]+) model=(\w+) card=(\S+)", out)
    assert m, out
    assert m.group(1) == "klc-review" and m.group(2) == "haiku"
    assert "D-G" in m.group(3)
    assert "\n" not in out.strip()      # --until keeps its one-line stop


def test_go_single_agent_stop_also_carries_the_dispatch_line(proj):
    _ticket(proj, "D-S", "review:work", "M")
    rc, out, err = _go(["D-S"])
    assert rc == 2, err
    assert "dispatch: agent=klc-review model=sonnet card=" in out


def test_go_skill_instructs_explicit_model():
    text = (FW / "klc-plugin" / "skills" / "go" / "SKILL.md").read_text(encoding="utf-8")
    assert "dispatch: agent=" in text
    assert re.search(r"Task\(subagent_type=<agent>, model=<model>, prompt=<card", text)
    assert "never omit `model=`" in text
