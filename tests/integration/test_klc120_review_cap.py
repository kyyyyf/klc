#!/usr/bin/env python3
"""KLC-120 step-4 — AC-5/AC-6: `scripts/review.py` refuses to write a job
card or dispatch any pass beyond `review.max_llm_passes` for the ticket's
track, unless the operator passes `--over-cap`; skipped passes never count
toward the cap (D-005)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))

import models as models_mod  # noqa: E402
import review as rv  # noqa: E402
import review_plan  # noqa: E402


def _seed_project(tmp_path: Path, *, track: str = "M") -> tuple[Path, Path]:
    project_root = tmp_path / "proj"
    (project_root / ".klc" / "config").mkdir(parents=True)
    (project_root / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")
    tdir = project_root / ".klc" / "tickets" / "KLC-990"
    tdir.mkdir(parents=True)
    meta = {
        "ticket": "KLC-990", "kind": "tech", "kind_source": "user",
        "phase": "review:work", "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    spec_path = tdir / "spec.md"
    spec_path.write_text("# spec\n", encoding="utf-8")
    return project_root, spec_path


def _write_diff(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _stub_claude_on_path(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


# A diff that classify_tier can't confidently score (no modules.json in a
# fresh tmp project), so review_cascade.decide's own fail-closed default
# ("classifier returned no file tiers ... defaulting to full review")
# naturally picks FULL review — no monkeypatch needed. This is real,
# observed behaviour of the shipped pipeline in a hermetic tmp_path
# project, not a test-only shortcut.
_HARMLESS_DIFF = (
    "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+docs update\n"
)


def _clear_keys(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_review_refuses_when_planned_exceeds_cap_without_override(tmp_path):
    """AC-5 (e2e): scripts/review.py CLI (subprocess), planned-pass count
    seeded above the M cap of 4 (the real generic manifest's four
    reviewers.always plus the external pass, five total on the full
    headless path) with no --over-cap. Exits non-zero, no job card, plan
    printed."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env["PROJECT_ROOT"] = str(project_root)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [sys.executable, str(FW_ROOT / "scripts" / "review.py"),
         "--diff", str(diff_path), "--spec", str(spec_path)],
        cwd=str(project_root), env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2
    assert "over the M cap of 4" in result.stderr
    job_cards = list((project_root / ".klc" / "reports").glob("pending-*/job-*.md"))
    assert job_cards == [], "no job card must be written when the run is refused"
    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    assert review_plan.counted(plan) == 5


def test_over_cap_plan_never_reaches_the_auto_dispatch_runner(tmp_path, monkeypatch):
    """AC-5 (acceptance): with RUN_LOCAL_SUBAGENTS=1 and a fake REVIEW_RUNNER
    that would prove it ran (writes a marker), an over-cap plan with no
    override exits refused and the runner is NEVER invoked — proves the
    "or dispatch any pass" half of AC-5."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("RUN_LOCAL_SUBAGENTS", "1")
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()

    marker = tmp_path / "dispatched.marker"
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('dispatched', encoding='utf-8')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REVIEW_RUNNER", str(fake_runner))
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path)])
    assert rc == 2
    assert not marker.exists(), "the cap must refuse before any dispatch is attempted"


def test_skipped_passes_never_count_toward_the_cap(tmp_path, monkeypatch):
    """AC-5/D-005 cross-check: on the client path the four manifest
    reviewers.always entries are always skipped, so only code-review,
    drift and external count — three against the M cap of four does not
    refuse."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--plan-only"])
    assert rc == 0

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review-plan.json").read_text(encoding="utf-8"))
    always_names = {"security", "architecture", "performance", "test-coverage"}
    skipped_always = [p for p in plan["passes"] if p["reviewer"] in always_names]
    assert len(skipped_always) == 4
    assert all(p["status"] == "skipped" for p in skipped_always)
    assert review_plan.counted(plan) <= plan["cap"]


def test_review_dispatches_over_cap_with_override_flag_and_records_cap_override(
        tmp_path):
    """AC-6 (e2e): scripts/review.py CLI with --over-cap dispatches the
    over-cap passes and the review report frontmatter carries
    cap_override: true with the cap value."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        "partial = Path(sys.argv[2])\n"
        "partial.write_text('## PASS\\nno findings\\n\\nTOTAL=0 BLOCKING=0\\n', "
        "encoding='utf-8')\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env["PROJECT_ROOT"] = str(project_root)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["RUN_LOCAL_SUBAGENTS"] = "1"
    env["REVIEW_RUNNER"] = str(fake_runner)

    result = subprocess.run(
        [sys.executable, str(FW_ROOT / "scripts" / "review.py"),
         "--diff", str(diff_path), "--spec", str(spec_path), "--over-cap"],
        cwd=str(project_root), env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    reports_dir = project_root / ".klc" / "reports"
    reports = sorted(reports_dir.glob("review-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "cap_override: true" in text
    assert "cap: 4" in text
    assert "planned_passes: 5" in text


def test_refused_run_leaves_previous_report_bytes_unchanged(tmp_path, monkeypatch):
    """Edge case: a refused dispatch (AC-5) leaves any previously written
    report untouched — verify file bytes are unchanged, not just the exit
    code."""
    project_root, spec_path = _seed_project(tmp_path, track="M")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("RUN_LOCAL_SUBAGENTS", "1")
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()

    reports_dir = project_root / ".klc" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    prior_report = reports_dir / "review-existing.md"
    prior_bytes = b"# a previously written report\nVerdict: APPROVED\n"
    prior_report.write_bytes(prior_bytes)

    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    monkeypatch.setenv("REVIEW_RUNNER", str(fake_runner))
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path)])
    assert rc == 2
    assert prior_report.read_bytes() == prior_bytes


def test_absent_max_llm_passes_key_means_no_cap():
    """Edge case: a track whose review.max_llm_passes key is entirely
    absent from config/reviewers.yml is treated as "no cap", not
    cap-zero."""
    assert review_plan.cap_for("M", {"review": {}}) is None
    assert review_plan.cap_for("M", {}) is None
    assert review_plan.cap_for(None, {"review": {"max_llm_passes": {"M": 4}}}) is None


def test_offline_rerun_hint_repeats_over_cap(tmp_path, monkeypatch, capsys):
    """D-014: the offline re-run hint repeats --over-cap when it was given,
    exactly as it already repeats --external, so a second, aggregating run
    of an overridden review doesn't refuse before it reaches the report."""
    project_root, spec_path = _seed_project(tmp_path, track="L")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path), "--over-cap"])
    assert rc == 0   # L's cap is 6; 5 passes on this diff does not refuse
    out = capsys.readouterr().out
    assert "--over-cap" in out


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
