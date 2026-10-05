"""KLC-179 step-5 (AC-8, AC-3): `klc status` renders facts and the next move.

A facts ticket and a legacy ticket (no `facts` key) both render one line per required
fact of the lane, the `blocked_on` fact and the next move; `board` and the metrics
rollup keep grouping and timing both shapes. Status never writes meta.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
KLC = _FW / "scripts" / "klc"
sys.path.insert(0, str(_FW / "core" / "skills"))

import rules  # noqa: E402


def _klc(root: Path, *args: str):
    env = {**os.environ, "PROJECT_ROOT": str(root)}
    env.pop("KLC_TICKETS_DIR", None)
    return subprocess.run([sys.executable, str(KLC), *args], capture_output=True,
                          text=True, env=env)


def _seed(root: Path, key: str, **meta) -> Path:
    tdir = root / ".klc" / "tickets" / key
    tdir.mkdir(parents=True)
    base = {"ticket": key, "kind": "tech", "kind_source": "user", "phase_history": [],
            "route_hint": "S", "affected_modules": [], "estimate": None,
            "jira_url": None, "created": "2026-01-01T00:00:00Z"}
    base.update(meta)
    (tdir / "meta.json").write_text(json.dumps(base), encoding="utf-8")
    return tdir / "meta.json"


def _facts_ticket(root: Path) -> Path:
    return _seed(root, "KLC-F1", track="S", phase="build:work",
                 facts={"track": "light", "spec_approved": True, "plan_reviewed": True})


def _legacy_ticket(root: Path) -> Path:
    return _seed(root, "KLC-L1", track="M", phase="discovery:ack-needed")


def test_status_renders_facts_and_next_move(tmp_path):
    _facts_ticket(tmp_path)
    r = _klc(tmp_path, "status", "KLC-F1")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "✓ spec_approved" in out and "✓ plan_reviewed" in out, out
    assert "· steps_green" in out and "· review_verdict" in out and "· merged" in out, out
    assert "test_plan_approved" not in out and "design_approved" not in out, out   # light lane
    assert "blocked_on" not in out, out
    assert "klc go KLC-F1" in out.splitlines()[-1], out          # the next move line
    assert "← now" in out


def test_status_legacy_ticket_shows_blocked_on_and_full_lane(tmp_path):
    meta = _legacy_ticket(tmp_path)
    before = meta.read_bytes()
    r = _klc(tmp_path, "status", "KLC-L1")
    assert r.returncode == 0, r.stderr
    for name in ("spec_approved", "test_plan_approved", "design_approved", "plan_reviewed"):
        assert name in r.stdout, r.stdout
    assert "blocked_on: spec_approved" in r.stdout, r.stdout
    assert meta.read_bytes() == before and "facts" not in json.loads(before)   # never write on read


def test_status_json_carries_facts_lane_blocked_on_next_move(tmp_path):
    _facts_ticket(tmp_path)
    _legacy_ticket(tmp_path)
    new = json.loads(_klc(tmp_path, "status", "KLC-F1", "--json").stdout)
    assert new["lane"] == "light" and new["blocked_on"] is None
    assert new["facts"]["spec_approved"] is True
    assert new["next_move"]["action"] == "build" and new["next_move"]["fact"] == "steps_green"
    old = json.loads(_klc(tmp_path, "status", "KLC-L1", "--json").stdout)
    assert old["lane"] == "full" and old["blocked_on"] == "spec_approved"
    assert old["next_move"]["action"] == "spec"
    assert old["phase"] == "discovery:ack-needed" and old["phase_id"] == "discovery"   # old keys stay


def test_status_terminal_branches_keep_working(tmp_path):
    _seed(tmp_path, "KLC-A1", track="S", phase="archived")
    _seed(tmp_path, "KLC-C1", track="S", phase="cancelled", cancel_reason="dup")
    a = _klc(tmp_path, "status", "KLC-A1")
    assert a.returncode == 0 and "archived" in a.stdout and "✓ merged" in a.stdout, a.stdout
    c = _klc(tmp_path, "status", "KLC-C1")
    assert c.returncode == 0 and "cancelled" in c.stdout and "dup" in c.stdout
    cj = json.loads(_klc(tmp_path, "status", "KLC-C1", "--json").stdout)
    assert cj["next_move"]["action"] == "done" and cj["phase"] == "cancelled"


def test_board_and_metrics_group_both_shapes(tmp_path):
    _facts_ticket(tmp_path)
    _legacy_ticket(tmp_path)
    hist = [{"phase": "intake:ack", "event": "ack", "at": "2026-01-01T00:00:00Z"},
            {"phase": "build:work", "event": "enter", "at": "2026-01-02T00:00:00Z"}]
    _seed(tmp_path, "KLC-L2", track="S", phase="archived", phase_history=hist)
    board = json.loads(_klc(tmp_path, "board", "--json").stdout)
    assert [e["key"] for e in board["build:work"]] == ["KLC-F1"]
    assert [e["key"] for e in board["discovery:ack-needed"]] == ["KLC-L1"]
    assert [e["key"] for e in board["archived"]] == ["KLC-L2"]
    r = _klc(tmp_path, "metrics", "--rollup")
    assert r.returncode == 0, r.stderr
    out = tmp_path / ".klc" / "knowledge" / "process-metrics.json"
    assert json.loads(out.read_text("utf-8"))


def test_status_facts_match_rules(tmp_path):
    """The rendered next move is the rule table's own answer."""
    _facts_ticket(tmp_path)
    out = json.loads(_klc(tmp_path, "status", "KLC-F1", "--json").stdout)
    move = rules.next_move(out["facts"], out["lane"], risk_tags=[])
    assert out["next_move"]["action"] == move.action
