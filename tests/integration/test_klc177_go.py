"""KLC-177 step-2 (AC-1..AC-4): `klc go <KEY>` moves a ticket one step from any state.

In-process with a tmp PROJECT_ROOT (feature-off). `gate_policy.collect_signals`
is patched so the gate verdict is the thing under test, not git or the index.
"""
from __future__ import annotations

import hashlib
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
    _flush()
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(_CLEAN))
    return tmp_path


def _signals(monkeypatch, sig):
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(sig))


def _ticket(root: Path, key: str, phase: str, track: str = "S", **files) -> Path:
    td = root / ".klc" / "tickets" / key
    td.mkdir(parents=True)
    meta = {"ticket": key, "kind": "feature", "phase": phase, "track": track,
            "route_confidence": "high", "affected_modules": [], "layer": "code",
            "budgets": {"mutation_fix_attempts": 0}, "risk_tags": [],
            "phase_history": [], "rework_count": {}}
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for rel, text in files.items():
        (td / rel).write_text(text, encoding="utf-8")
    return td


def _go(argv):
    import go
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = int(go.run(list(argv)))
    return rc, out.getvalue(), err.getvalue()


def _status(key):
    import status
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        status.run([key])
    return out.getvalue()


def _phase(td: Path) -> str:
    return json.loads((td / "meta.json").read_text(encoding="utf-8"))["phase"]


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_go_from_ack_and_clean_ack_needed_advances(proj):
    td = _ticket(proj, "G-1", "review:ack")
    rc, out, err = _go(["G-1"])
    assert rc == 0, err
    assert _phase(td) == "integrate:work"
    assert "cat " in out

    td2 = _ticket(proj, "G-2", "build:ack-needed")        # conditional gate, clean
    rc, out, err = _go(["G-2"])
    assert rc == 0, err
    assert _phase(td2) == "review:work"
    assert "cat " in out


def test_go_from_work_acks_when_outputs_complete_and_stops_when_missing(proj):
    # KLC-179: observe belongs to the full lane only; the retrospective follows it there
    td = _ticket(proj, "G-3", "observe:work", track="M")  # no declared outputs, conditional
    rc, out, err = _go(["G-3"])
    assert rc == 0, err
    assert _phase(td) == "learn:work"

    td2 = _ticket(proj, "G-4", "review:work")             # review-report.md missing
    before = (td2 / "meta.json").read_bytes()
    rc, out, err = _go(["G-4"])
    assert rc == 2
    assert (td2 / "meta.json").read_bytes() == before
    assert "_prompt.md" in out and "review" in out


def test_go_refuses_decision_gate_and_dirty_gate_without_pick(proj, monkeypatch):
    td = _ticket(proj, "G-5", "discovery:ack-needed", track="M")      # decision gate
    before = (td / "meta.json").read_bytes()
    rc, out, err = _go(["G-5"])
    assert rc == 2
    assert (td / "meta.json").read_bytes() == before
    assert "--pick" in (out + err) and "1=" in (out + err)
    rc, out, err = _go(["G-5", "--pick", "1"])                         # positive twin
    assert rc == 0, err
    assert _phase(td) == "acceptance-test-plan:work"

    _signals(monkeypatch, _HIGH)                                       # dirty conditional
    td2 = _ticket(proj, "G-6", "build:ack-needed")
    before = (td2 / "meta.json").read_bytes()
    rc, out, err = _go(["G-6"])
    assert rc == 2
    assert (td2 / "meta.json").read_bytes() == before
    assert "advisory" in (out + err) and "--pick" in (out + err)
    rc, out, err = _go(["G-6", "--pick", "1"])
    assert rc == 0, err
    assert _phase(td2) == "review:work"

    # KLC-179: the design approval is a decision point
    td3 = _ticket(proj, "G-7", "design:ack-needed", track="M")
    before = (td3 / "meta.json").read_bytes()
    rc, out, err = _go(["G-7"])
    assert rc == 2
    assert (td3 / "meta.json").read_bytes() == before

    # F-003: integrate is conditional but its gate checks the merge; with no recorded
    # range (or an unmerged branch) one plain `klc go` must not archive the ticket
    td4 = _ticket(proj, "G-7b", "integrate:work")
    before = (td4 / "meta.json").read_bytes()
    rc, out, err = _go(["G-7b"])
    assert rc == 2
    assert (td4 / "meta.json").read_bytes() == before


def test_go_dry_run_writes_nothing_and_matches_status(proj):
    for key, phase in (("D-1", "review:work"), ("D-2", "build:ack-needed"),
                       ("D-3", "review:ack"), ("D-4", "observe:work")):
        _ticket(proj, key, phase)
        before = _tree_hash(proj)
        rc, out, err = _go([key, "--dry-run"])
        assert rc == 0, err
        assert _tree_hash(proj) == before
        line = out.strip()
        assert "\n" not in line and line
        assert _status(key).rstrip("\n").splitlines()[-1] == line


def test_go_reason_becomes_ack_note_when_note_absent(proj):
    td = _ticket(proj, "G-8", "build:ack-needed")
    rc, _, err = _go(["G-8", "--reason", "looks fine to me"])
    assert rc == 0, err
    hist = json.loads((td / "meta.json").read_text(encoding="utf-8"))["phase_history"]
    assert any("looks fine to me" in (h.get("note") or "") for h in hist)


def test_go_on_terminal_ticket_prints_done_and_exits_zero(proj):
    td = _ticket(proj, "G-9", "archived")
    before = (td / "meta.json").read_bytes()
    rc, out, err = _go(["G-9"])
    assert rc == 0
    assert "archived" in out
    assert (td / "meta.json").read_bytes() == before


def test_go_is_registered_in_the_dispatcher(proj):
    import subprocess
    _ticket(proj, "G-10", "review:ack")
    r = subprocess.run([sys.executable, str(_FW / "scripts" / "klc"), "go", "G-10", "--dry-run"],
                       capture_output=True, text=True, env={**__import__("os").environ, "PROJECT_ROOT": str(proj)})
    assert r.returncode == 0, r.stderr
    assert "klc go G-10" in r.stdout
