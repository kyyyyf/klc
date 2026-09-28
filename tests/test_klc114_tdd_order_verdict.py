"""KLC-114 step-3: judge_step records red-before-green ordering violations
carrying tdd_order's own reason verbatim, never a re-paraphrase (AC-3)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402
import tdd_order as td  # noqa: E402


def test_impl_before_red_commit_yields_red_with_tdd_order_reason(tmp_path, monkeypatch):
    """AC-3: an impl commit with no preceding failing-test commit → red,
    carrying the EXACT reason `tdd_order.verify_step` returned — never a
    re-paraphrase, and never green."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-TO01"
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", affected="`core/skills/x.py`")
    h.make_ticket(tmp_path, ticket, "M", plan)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"core/skills/x.py": "# impl, no test committed first"},
             f"{ticket} step-1: add impl")

    expected_ok, expected_reason = td.verify_step(ticket, 1, repo)
    assert not expected_ok, "fixture must actually violate red-before-green"

    v = sl.judge_step(ticket, 1, repo=str(repo))

    assert v.state == sl.RED
    assert v.reason == expected_reason
