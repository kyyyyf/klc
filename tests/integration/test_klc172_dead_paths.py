"""KLC-172 step-2: dead modules/templates gone, severity rubric under config/,
ad-hoc ticket logs ignored by state_sync."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "core" / "skills"))

DEAD_TEMPLATES = ["spec", "spec-short", "test-plan", "test-plan-short",
                  "options", "retrospective", "ticket-readme",
                  "step-review-package"]


def test_dead_modules_and_templates_are_gone():
    assert not (FW / "core/skills/findings_migrate.py").exists()
    for name in DEAD_TEMPLATES:
        assert not (FW / "core/templates" / f"{name}.md.j2").exists(), name
    out = subprocess.run([sys.executable, str(FW / "core/skills/handback.py"), "--help"],
                         capture_output=True, text=True)
    assert "migrate" not in (out.stdout + out.stderr)
    assert not list((FW / "tests").rglob("test_klc154_*.py"))


def test_severity_rubric_path_exists_and_is_referenced():
    assert (FW / "config/severity-rubric.md").is_file()
    assert not (FW / "docs/severity-rubric.md").exists()
    review = (FW / "scripts/review.py").read_text(encoding="utf-8")
    assert '"config" / "severity-rubric.md"' in review or "config/severity-rubric.md" in review
    per_step = (FW / "core/agents/review/per-step.md").read_text(encoding="utf-8")
    assert "config/severity-rubric.md" in per_step
    assert "docs/severity-rubric.md" not in per_step


def test_state_sync_ignores_adhoc_ticket_logs():
    import state_sync
    for pat in ("full_suite_run*.log", "codex_*.md", "measure/"):
        assert pat in state_sync._DERIVED_IGNORES, pat
    specs = state_sync._derived_match_pathspecs()
    assert ":(glob)**/full_suite_run*.log" in specs
    assert ":(glob)**/codex_*.md" in specs
    assert ":(glob)**/measure/**" in specs
    excl = state_sync.derived_add_exclude_pathspecs()
    assert ":(exclude,glob)**/codex_*.md" in excl


def test_no_stale_migrate_advice_or_orphan_klc154_support():
    """KLC-172 review round 1 (F-011)."""
    spec_review = (FW / "core/skills/spec_review.py").read_text(encoding="utf-8")
    assert "handback.py migrate" not in spec_review
    assert not (FW / "tests/integration/_klc154_support.py").exists()
    assert not (FW / "tests/fixtures/klc154-corpus").exists()
    proc = (FW / "docs/process.md").read_text(encoding="utf-8")
    assert "token_backfill" not in proc
