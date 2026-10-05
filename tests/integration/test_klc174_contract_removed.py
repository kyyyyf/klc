"""KLC-174 step-3 (AC-7): the Evidence replay and the progress ledger are gone.

Step-4 adds the `phases.yml` half of AC-7 (`build/steps.json` is the build
output) and the AC-9 prompt contract.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
SKILLS = FW / "core" / "skills"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(FW / "tests"))

import klc114_helpers as h  # noqa: E402

REMOVED = ("evidence_gate", "step_verify", "step_ledger", "build_ledger")


def test_evidence_machinery_gone_and_build_log_optional(tmp_path, monkeypatch):
    # 1. the four modules no longer exist, on disk or importable
    for name in REMOVED:
        assert not (SKILLS / f"{name}.py").exists(), name
        assert importlib.util.find_spec(name) is None, name

    # 2. the knobs only they used are gone; the budgets that survive stay
    import settings
    import verify_runner
    assert not hasattr(settings, "verify_entry_budget")
    assert not hasattr(settings, "build_verify_steps")
    assert callable(settings.verify_arm_budget) and callable(settings.verify_step_budget)
    assert not hasattr(verify_runner, "run_cached")
    assert callable(verify_runner.run) and callable(verify_runner.spawn)

    # 3. no source file imports a removed module
    for py in list(SKILLS.glob("*.py")) + list((FW / "core" / "phases").glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for name in REMOVED:
            assert f"import {name}" not in text and f"from {name} " not in text, (py.name, name)

    # 4. a ticket with no build-log.md and no Evidence section acks, and the
    #    orchestrator writes no progress.md
    import build_orchestrator
    import phase_completion
    import step_state
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    plan = "# Implementation plan\n\n" + h.step_plan("step-1", affected="`src.py`")
    tdir = h.make_ticket(tmp_path, "KLC-RM1", "XS", plan)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "def test_a():\n    assert True\n"},
             "KLC-RM1 step-1: add failing tests")
    h.commit(repo, {"src.py": "x = 1\n"}, "KLC-RM1 step-1: do the thing")
    h.seed_steps(tdir, repo)
    assert not (tdir / "build-log.md").exists()
    ok, msg = phase_completion.can_complete_build("KLC-RM1", repo, persist=False)
    assert ok, msg
    assert [r["state"] for r in step_state.derive("KLC-RM1", repo)] == ["green"]
    assert not (tdir / "build" / "progress.md").exists()
    assert build_orchestrator._judge_step and not hasattr(build_orchestrator, "Ledger")


def test_impl_prompt_describes_steps_json_contract():
    impl = (FW / "core/agents/impl.md").read_text(encoding="utf-8")
    assert "klc step verify" in impl and "build/steps.json" in impl
    assert "## Evidence" not in impl
    assert "entry_budget_seconds" not in impl and "RE-EXECUTES" not in impl
    xs = (FW / "core/agents/xs-fasttrack.md").read_text(encoding="utf-8")
    assert "## Evidence" not in xs


def test_phases_yml_build_output_is_steps_json():
    import yaml
    phases = yaml.safe_load((FW / "config/phases.yml").read_text(encoding="utf-8"))
    rows = phases["phases"] if isinstance(phases, dict) and "phases" in phases else phases
    build = next(p for p in rows if p["id"] == "build")
    assert build["outputs"] == ["build/steps.json"]
