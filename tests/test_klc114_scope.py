"""KLC-114 / KLC-174: scope-violation handling at build ack.

KLC-174 dropped the per-step scope-violation advisory together with
`step_ledger` (the out-of-scope paths of a step are still checked by the
independent drift check and review). What survives, and what this file pins:
a step that touches a path outside its declared `Affected:` list never
becomes a build-ack breach, and the ack no longer carries a scope advisory.
The directory-only test-path classification `step_ledger` used lives on in
tests/integration/test_klc174_kept_behaviours.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402


def test_ack_still_passes_when_scope_violation_report_only(tmp_path, monkeypatch):
    """Q-004 negative twin (KLC-174 form): a step whose commits touch an undeclared
    path still lets `can_complete_build` return a truthy verdict, and the verdict
    carries no scope advisory — the report-only scope note is gone."""
    import json
    from core.skills.phase_completion import can_complete_build

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SV01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        "---\nticket: KLC-SV01\nkind: tech\n---\n\n## Acceptance Criteria\n\n"
        "## Estimate\n- total: 1\n", encoding="utf-8")
    (ticket_dir / "test-plan.md").write_text(
        "---\nticket: KLC-SV01\nkind: test-plan\n---\n\n## Acceptance coverage\n\n"
        "## Edge cases\n- n/a\n", encoding="utf-8")
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`sh -c \"echo 2 passed\"`", expected="`2 passed`",
        affected="`core/skills/x.py`")
    (ticket_dir / "impl-plan.md").write_text(plan, encoding="utf-8")
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")
    h.commit(repo, {"core/skills/x.py": "# impl",
                    "core/skills/undeclared_helper.py": "# stray"},
             f"{ticket} step-1: add impl")
    h.seed_steps(ticket_dir, repo)

    ok, msg = can_complete_build(ticket, repo=str(repo))

    assert ok, msg
    assert "scope" not in msg.lower()
    assert "undeclared_helper" not in msg
