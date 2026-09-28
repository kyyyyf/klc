#!/usr/bin/env python3
"""KLC-120 review-fix round 1, HIGH finding (AC-3/AC-4): review_plan.record_pass
(the in-client `review_plan.py record --ticket K --reviewer R` CLI) must not
trust the caller. It refuses — non-zero exit, a stderr message, and no
attempt written — when review-plan.json is missing, R is not one of its
passes, or R's status is `skipped`. A repeated record of an already-`executed`
pass stays a no-op success (idempotent, D-120-10); the existing happy path
lives in test_klc120_review_prompt_instructions.py and is unchanged."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import metrics  # noqa: E402


def _seed_ticket(project_root: Path, ticket: str) -> Path:
    tdir = project_root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "review:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    return tdir


def _write_plan(tdir: Path, passes: list) -> None:
    plan = {
        "ticket": tdir.name, "track": "M", "path": "client",
        "generated_at": "2026-01-01T00:00:00Z", "diff_sha256": "abc123",
        "cap": None, "override": False, "per_step_build_review": "not counted",
        "cascade": None, "notes": [], "passes": passes,
    }
    (tdir / "review-plan.json").write_text(json.dumps(plan, indent=2) + "\n",
                                           encoding="utf-8")


def _run_record(project_root: Path, ticket: str, reviewer: str):
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(project_root)
    return subprocess.run(
        [sys.executable, str(FW_ROOT / "core" / "skills" / "review_plan.py"),
         "record", "--ticket", ticket, "--reviewer", reviewer],
        cwd=str(project_root), env=env, capture_output=True, text=True,
        timeout=30,
    )


def _tagged_attempts(project_root: Path, ticket: str, reviewer: str) -> list:
    meta_path = project_root / ".klc" / "tickets" / ticket / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return [rec for _phase, rec in metrics.iter_attempts(meta, ticket)
            if rec.get("reviewer") == reviewer]


def test_record_refuses_when_no_plan_exists(tmp_path, monkeypatch):
    """(a) no review-plan.json at all — non-zero exit, no attempt written."""
    project_root = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    _seed_ticket(project_root, "KLC-996")

    result = _run_record(project_root, "KLC-996", "totally-fake-reviewer-nobody-ran")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert _tagged_attempts(project_root, "KLC-996",
                            "totally-fake-reviewer-nobody-ran") == []


def test_record_refuses_for_unknown_reviewer(tmp_path, monkeypatch):
    """(b) a plan exists but names no such reviewer — non-zero exit, no
    attempt written."""
    project_root = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    tdir = _seed_ticket(project_root, "KLC-997")
    _write_plan(tdir, [
        {"reviewer": "code-review", "source": "independent",
         "selected_by": "CLAUDE.md mandatory fresh reviewer",
         "provider": None, "model": None, "status": "planned"},
    ])

    result = _run_record(project_root, "KLC-997", "totally-fake-reviewer-nobody-ran")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert _tagged_attempts(project_root, "KLC-997",
                            "totally-fake-reviewer-nobody-ran") == []


def test_record_refuses_for_skipped_reviewer(tmp_path, monkeypatch):
    """(c) the named reviewer is in the plan but status `skipped` — non-zero
    exit, no attempt written."""
    project_root = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    tdir = _seed_ticket(project_root, "KLC-998")
    _write_plan(tdir, [
        {"reviewer": "deep-impact", "source": "manifest-conditional",
         "selected_by": "no trigger fired", "provider": None, "model": None,
         "status": "skipped", "skip_reason": "no trigger fired"},
    ])

    result = _run_record(project_root, "KLC-998", "deep-impact")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert _tagged_attempts(project_root, "KLC-998", "deep-impact") == []


def test_record_of_already_executed_pass_is_a_noop_success(tmp_path, monkeypatch):
    """A pass already marked `executed` (e.g. a retried in-client `record`
    call) is a no-op success: exit 0, the SAME attempt id, and no second
    attempt written."""
    project_root = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    tdir = _seed_ticket(project_root, "KLC-999")
    _write_plan(tdir, [
        {"reviewer": "code-review", "source": "independent",
         "selected_by": "CLAUDE.md mandatory fresh reviewer",
         "provider": None, "model": None, "status": "planned"},
    ])

    r1 = _run_record(project_root, "KLC-999", "code-review")
    assert r1.returncode == 0, r1.stderr
    r2 = _run_record(project_root, "KLC-999", "code-review")
    assert r2.returncode == 0, r2.stderr
    assert r1.stdout.strip() == r2.stdout.strip()

    tagged = _tagged_attempts(project_root, "KLC-999", "code-review")
    assert len(tagged) == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
