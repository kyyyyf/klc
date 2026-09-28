"""KLC-114 step-1: step_ledger.judge_step re-executes a step's VERIFY command
and requires the Expected outcome token in the captured output (AC-4)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402


def test_green_requires_rerun_pass_and_expected_token_present(tmp_path, monkeypatch):
    """AC-4: green only after the re-run exits 0 AND the Expected token is
    present in the captured output — not on exit status alone."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-LG01"
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`python3 -c \"print('2 passed in 0.01s')\"`",
        expected="`2 passed`")
    h.make_ticket(tmp_path, ticket, "M", plan)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")

    v = sl.judge_step(ticket, 1, repo=str(repo))

    assert v.state == sl.GREEN, v.reason
    assert v.step_id == "step-1"


def test_rerun_passes_but_token_absent_is_red(tmp_path, monkeypatch):
    """AC-4: the re-run exits 0 but the Expected token is absent from the
    captured output — must be red, never green, on exit status alone."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-LG02"
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`python3 -c \"print('1 passed in 0.01s')\"`",
        expected="`2 passed`")
    h.make_ticket(tmp_path, ticket, "M", plan)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")

    v = sl.judge_step(ticket, 1, repo=str(repo))

    assert v.state == sl.RED
    assert "token" in v.reason
