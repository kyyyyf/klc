"""KLC-174 step-1 (AC-1): `klc step verify <KEY> N` records an allowlisted VERIFY."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FW = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW / "core" / "phases"))

PLAN = """## step-1 — thing

- Goal: g
- RED: tests/test_a.py::test_a
- VERIFY: `python3 -m pytest tests/test_a.py -q`
- COMMIT: KLC-T2 step-1: thing
"""


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


def _fixture(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T2"
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps({"ticket": "KLC-T2", "phase": "build"}))
    (tdir / "impl-plan.md").write_text(PLAN, encoding="utf-8")
    return tdir


def test_step_verify_records_allowlisted_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _fixture(tmp_path)
    import step

    rc = step.run(["verify", "KLC-T2", "1"])
    assert rc == 0
    data = json.loads((tdir / "build" / "steps.json").read_text())
    v = data["steps"]["1"]["verify"]
    assert set(v) == {"command", "exit_code", "summary_line", "ran_at", "runner", "head", "dirty"}
    assert v["command"] == "python3 -m pytest tests/test_a.py -q"
    assert v["exit_code"] == 0
    assert "1 passed" in v["summary_line"]
    assert v["runner"] == "agent"
    assert v["ran_at"].endswith("Z")


def test_failing_verify_is_recorded_and_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _fixture(tmp_path)
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert False\n")
    import step

    assert step.run(["verify", "KLC-T2", "1"]) == 1
    v = json.loads((tdir / "build" / "steps.json").read_text())["steps"]["1"]["verify"]
    assert v["exit_code"] == 1 and "failed" in v["summary_line"]


def test_unknown_step_and_ticket_are_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _fixture(tmp_path)
    import step

    assert step.run(["verify", "KLC-T2", "9"]) == 1
    assert step.run(["verify", "KLC-NOPE", "1"]) == 1


def test_derive_recomputes_from_git_and_check_build(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _fixture(tmp_path)
    import step
    import step_state

    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        _git(tmp_path, *a)
    ok, why = step_state.check_build("KLC-T2", tmp_path)
    assert not ok and why.startswith("step-1: pending")
    _git(tmp_path, "add", "tests/test_a.py")
    _git(tmp_path, "commit", "-qm", "KLC-T2 step-1: add failing tests")
    assert step_state.derive("KLC-T2", tmp_path)[0]["state"] == "red"
    (tmp_path / "src.py").write_text("x = 1\n")
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-qm", "KLC-T2 step-1: thing")
    ok, why = step_state.check_build("KLC-T2", tmp_path)
    assert not ok and "no recorded verify" in why
    assert step.run(["verify", "KLC-T2", "1"]) == 0
    assert step_state.check_build("KLC-T2", tmp_path) == (True, "")
    # a forged file claiming a different command / exit code is never trusted
    p = tdir / "build" / "steps.json"
    data = json.loads(p.read_text())
    data["steps"]["1"]["verify"]["command"] = "echo hi"
    p.write_text(json.dumps(data))
    assert step_state.check_build("KLC-T2", tmp_path)[0] is False
    p.write_text("[1, 2]")
    assert step_state.check_build("KLC-T2", tmp_path)[0] is False
