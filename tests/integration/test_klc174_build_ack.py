"""KLC-174 step-2 (AC-2, AC-4, AC-5, AC-6): the build ack reads steps.json and executes nothing."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW / "tests"))

import klc114_helpers as h  # noqa: E402

KEY = "KLC-T5"
VERIFY = "python3 -m pytest tests/test_a.py -q"

PLAN = (
    "## step-1 — thing\n\n- Goal: g\n- RED: `tests/test_a.py::test_a`\n- GREEN: do it\n"
    f"- VERIFY: `{VERIFY}`\n- COMMIT: `{KEY} step-1: thing`\n- Affected: `src.py`\n"
    "- Interfaces: none\n- Expected: `1 passed`\n- Depends on: none\n\n"
    "```python\n# sketch\npass\n```\n\n"
)


def _ts(delta_s: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_steps(tdir: Path, verify: dict | None, raw: str | None = None) -> None:
    (tdir / "build").mkdir(exist_ok=True)
    if isinstance(verify, dict) and "head" not in verify:
        repo = tdir.parents[2]          # <repo>/.klc/tickets/<KEY>
        verify = {**verify, "head": h._run(["git", "rev-parse", "HEAD"], repo) or None,
                  "dirty": False}
    body = raw if raw is not None else json.dumps({"steps": {"1": {"step": 1, "verify": verify}}})
    (tdir / "build" / "steps.json").write_text(body, encoding="utf-8")


def _good(**over) -> dict:
    v = {"command": VERIFY, "exit_code": 0, "summary_line": "1 passed", "ran_at": _ts(60),
         "runner": "agent"}
    v.update(over)
    return v


def _init(repo: Path) -> None:
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        h._run(["git", *a], repo)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = h.make_ticket(tmp_path, KEY, "XS", PLAN)
    _init(tmp_path)
    h.commit(tmp_path, {"tests/test_a.py": "def test_a():\n    assert True\n"},
             f"{KEY} step-1: add failing tests")
    h.commit(tmp_path, {"src.py": "x = 1\n"}, f"{KEY} step-1: thing")
    return tmp_path, tdir


def _ack(repo, persist=False):
    import phase_completion
    return phase_completion.can_complete_build(KEY, repo, persist=persist)


def test_ack_spawns_nothing_for_stored_command(tmp_path, monkeypatch):
    """A stored sentinel command is never run: it would fail / create a file if it were."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    sentinel = "touch SENTINEL_FILE"
    plan = PLAN.replace(VERIFY, sentinel)
    tdir = h.make_ticket(tmp_path, KEY, "XS", plan)
    _init(tmp_path)
    h.commit(tmp_path, {"tests/test_a.py": "def test_a():\n    assert True\n"},
             f"{KEY} step-1: add failing tests")
    h.commit(tmp_path, {"src.py": "x = 1\n"}, f"{KEY} step-1: thing")
    _write_steps(tdir, _good(command=sentinel))
    import verify_runner

    def boom(*a, **k):
        raise AssertionError("ack must not execute a stored command")

    for name in ("run", "spawn", "run_cached"):
        if hasattr(verify_runner, name):
            monkeypatch.setattr(verify_runner, name, boom)
    ok, msg = _ack(tmp_path, persist=True)
    assert ok, msg
    assert not (tmp_path / "SENTINEL_FILE").exists()


def test_no_build_log_and_no_evidence_section_is_fine(env):
    repo, tdir = env
    _write_steps(tdir, _good())
    assert not (tdir / "build-log.md").exists()
    ok, msg = _ack(repo)
    assert ok, msg


@pytest.mark.parametrize("case", ["no_commit", "foreign_command", "ran_before_commit"])
def test_tampered_steps_json_blocks(tmp_path, monkeypatch, case):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = h.make_ticket(tmp_path, KEY, "XS", PLAN)
    _init(tmp_path)
    if case != "no_commit":
        h.commit(tmp_path, {"tests/test_a.py": "def test_a():\n    assert True\n"},
                 f"{KEY} step-1: add failing tests")
        h.commit(tmp_path, {"src.py": "x = 1\n"}, f"{KEY} step-1: thing")
    else:
        h.commit(tmp_path, {"README": "x\n"}, "unrelated")
    over = {"foreign_command": {"command": "echo 1 passed"},
            "ran_before_commit": {"ran_at": "2000-01-01T00:00:00Z"}}.get(case, {})
    _write_steps(tdir, _good(**over))
    ok, msg = _ack(tmp_path)
    assert not ok
    assert "step-1" in msg


@pytest.mark.parametrize("case", ["missing", "failed", "corrupt", "list"])
def test_missing_or_failed_verify_blocks_naming_step(env, case):
    repo, tdir = env
    if case == "failed":
        _write_steps(tdir, _good(exit_code=1, summary_line="1 failed"))
    elif case == "corrupt":
        _write_steps(tdir, None, raw="{not json")
    elif case == "list":
        _write_steps(tdir, None, raw="[1, 2]")
    ok, msg = _ack(repo)
    assert not ok
    assert "step-1" in msg
    assert "\n" not in msg


def test_tdd_order_and_ac_coverage_still_block(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = h.make_ticket(tmp_path, KEY, "M", PLAN)
    _init(tmp_path)
    h.commit(tmp_path, {"src.py": "x = 1\n"}, f"{KEY} step-1: thing")          # impl first
    h.commit(tmp_path, {"tests/test_a.py": "def test_a():\n    assert True\n"},
             f"{KEY} step-1: add tests")
    _write_steps(tdir, _good())
    ok, msg = _ack(tmp_path)
    assert not ok and msg.startswith("TDD order:")

    # AC coverage: order fixed, the coverage check blocks and is called with run_tests=persist
    import ac_test_coverage

    calls = []

    class Rep:
        block_reason = "AC-1 has no implemented test"

    def fake(ticket, track, repo=None, **kw):
        calls.append(kw)
        return Rep()

    monkeypatch.setattr(ac_test_coverage, "check", fake)
    plan = PLAN.replace("- RED: `tests/test_a.py::test_a`", "- RED: not applicable")
    (tdir / "impl-plan.md").write_text(plan, encoding="utf-8")
    ok, msg = _ack(tmp_path, persist=True)
    assert not ok and msg.startswith("AC coverage:")
    assert calls and calls[0].get("run_tests") is True
