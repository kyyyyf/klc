"""KLC-114 step-7: `run_build` marks a step green only on the ledger pass's
verdict for that step — never on a zero return code from `dispatch` alone
(AC-8)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import klc114_helpers as h  # noqa: E402


def test_fake_dispatch_returns_zero_but_verify_fails_step_not_green(tmp_path, monkeypatch):
    """AC-8: a fake `dispatch` that returns 0 for a step whose VERIFY re-run
    genuinely fails must leave that step's ledger state NOT green."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-RG01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:work", "track": "XS",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code", "risk_tags": [],
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        f"---\nticket: {ticket}\nkind: tech\n---\n\n"
        "## Goals\nDo the thing.\n\n## Acceptance Criteria\n- [ ] AC-1: does the thing.\n",
        encoding="utf-8")
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`sh -c \"exit 1\"`", expected="`2 passed`",
        affected="`core/skills/x.py`")
    (ticket_dir / "impl-plan.md").write_text(plan, encoding="utf-8")

    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")
    h.commit(repo, {"core/skills/x.py": "# impl"}, f"{ticket} step-1: add impl")
    monkeypatch.chdir(repo)

    def fake_dispatch(phase_id, prompt_path, out_path, *, track=None, inputs=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0  # the builder claims success; the real VERIFY disagrees

    import build_orchestrator as bo
    rc = bo.run_build(ticket, dispatch=fake_dispatch)

    assert rc != 0

    from build_ledger import Ledger
    led = Ledger.load(ticket)
    assert led.steps[0].state != "green", led.steps[0]
