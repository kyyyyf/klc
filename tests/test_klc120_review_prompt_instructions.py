#!/usr/bin/env python3
"""KLC-120 step-5 — AC-11: core/agents/review.md and external-review.md
(and their klc-plugin/agents/ twins) instruct the in-client orchestrator
to run the planner first, run only planned passes, record one tagged
attempt per executed pass, and run the external pass on the resolved
Claude model. Also pins review_plan.py's `record` CLI (AC-3) and the
byte ceiling of the two edited plugin twins (D-016)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import metrics  # noqa: E402

CORE_AGENTS = FW_ROOT / "core" / "agents"
PLUGIN_AGENTS = FW_ROOT / "klc-plugin" / "agents"


def test_review_and_external_review_prompts_instruct_planner_first_and_tagged_attempts():
    """AC-11: core/agents/review.md and its plugin twin instruct running
    the planner first and recording one tagged attempt per executed
    pass."""
    for path in (CORE_AGENTS / "review.md", PLUGIN_AGENTS / "review.md"):
        text = path.read_text(encoding="utf-8")
        assert "--plan-only" in text, f"{path} missing the planner-first instruction"
        assert "review_plan.py record" in text, f"{path} missing the record instruction"
        assert "review.max_llm_passes" in text, f"{path} missing the cap reference"


def test_external_review_prompt_names_resolved_claude_model_and_claude_cli_route():
    """AC-11: core/agents/external-review.md and its plugin twin run the
    external pass on the resolved Claude model through the claude CLI."""
    for path in (CORE_AGENTS / "external-review.md", PLUGIN_AGENTS / "external-review.md"):
        text = path.read_text(encoding="utf-8")
        assert "resolved model" in text, f"{path} missing the resolved-model instruction"
        assert "claude` CLI" in text, f"{path} missing the claude CLI route"


def test_review_prompt_gate_is_provider_aware_not_api_key_env_only():
    """AC-11/D-009: the review prompt's external-reviewer gate names both
    the openai/google key check and the anthropic claude-CLI check — it no
    longer describes a bare api_key_env-only gate."""
    for path in (CORE_AGENTS / "review.md", PLUGIN_AGENTS / "review.md"):
        text = path.read_text(encoding="utf-8")
        assert "api_key_env" not in text, \
            f"{path} still describes the pre-KLC-120 api_key_env-only gate"
        assert "openai" in text and "google" in text
        assert "claude` CLI is not on PATH" in text


def test_edited_plugin_twins_stay_within_main_byte_total():
    """D-016: the two edited plugin twins stay at or below their combined
    size on main (16 413 bytes) — the saving in external-review.md pays
    for review.md's new planner-first step."""
    total = ((PLUGIN_AGENTS / "review.md").stat().st_size
             + (PLUGIN_AGENTS / "external-review.md").stat().st_size)
    assert total <= 16_413, f"plugin twins grew to {total} bytes (ceiling 16413)"


def test_process_md_review_documents_plan_cap_and_over_cap_flag():
    """AC-11 companion: docs/process.md documents the plan, the cap
    defaults and --over-cap."""
    text = (FW_ROOT / "docs" / "process.md").read_text(encoding="utf-8")
    assert "review-plan.json" in text
    assert "--over-cap" in text
    assert "max_llm_passes" in text
    assert "review_llm_passes_per_ticket" in text


def test_record_cli_appends_one_tagged_attempt_and_marks_pass_executed(
        tmp_path, monkeypatch):
    """AC-3: python3 core/skills/review_plan.py record --ticket <KEY>
    --reviewer <name> appends exactly one reviewer-tagged attempt and
    marks the pass executed in review-plan.json; a repeated call for the
    same run is idempotent (same attempt id, still one tagged attempt)."""
    project_root = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    tdir = project_root / ".klc" / "tickets" / "KLC-995"
    tdir.mkdir(parents=True)
    meta = {
        "ticket": "KLC-995", "kind": "tech", "kind_source": "user",
        "phase": "review:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    plan = {
        "ticket": "KLC-995", "track": "M", "path": "client",
        "generated_at": "2026-01-01T00:00:00Z", "diff_sha256": "abc123",
        "cap": None, "override": False, "per_step_build_review": "not counted",
        "cascade": None, "notes": [],
        "passes": [
            {"reviewer": "code-review", "source": "independent",
             "selected_by": "CLAUDE.md mandatory fresh reviewer",
             "provider": None, "model": None, "status": "planned"},
        ],
    }
    (tdir / "review-plan.json").write_text(json.dumps(plan, indent=2) + "\n",
                                           encoding="utf-8")

    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(project_root)

    def _run():
        return subprocess.run(
            [sys.executable, str(FW_ROOT / "core" / "skills" / "review_plan.py"),
             "record", "--ticket", "KLC-995", "--reviewer", "code-review"],
            cwd=str(project_root), env=env, capture_output=True, text=True,
            timeout=30,
        )

    r1 = _run()
    assert r1.returncode == 0, r1.stderr
    r2 = _run()
    assert r2.returncode == 0, r2.stderr
    assert r1.stdout.strip() == r2.stdout.strip(), \
        "the same run's record call must be idempotent (same attempt id)"

    meta_after = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    tagged = [rec for _phase, rec in metrics.iter_attempts(meta_after, "KLC-995")
              if rec.get("reviewer") == "code-review"]
    assert len(tagged) == 1, \
        "two record calls for the same pass of the same run must collapse to one attempt"

    plan_after = json.loads((tdir / "review-plan.json").read_text(encoding="utf-8"))
    entry = next(p for p in plan_after["passes"] if p["reviewer"] == "code-review")
    assert entry["status"] == "executed"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
