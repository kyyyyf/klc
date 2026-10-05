#!/usr/bin/env python3
"""KLC-120 step-4 — AC-7: the rendered review report states the planned
pass count, the executed pass count and every skipped pass with its
reason, on the headless path. D-015: a runner-failure partial is not
counted executed."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))

import models as models_mod  # noqa: E402
import review as rv  # noqa: E402


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


def _clear_keys(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


_HARMLESS_DIFF = (
    "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+docs update\n"
)


def test_headless_review_report_states_planned_executed_and_skipped_with_reason(
        tmp_path, monkeypatch):
    """AC-7 (e2e row): the headless report states planned/executed counts
    and every skipped pass with its reason."""
    project_root, spec_path = _seed_project(tmp_path, track="L")  # cap 6: no refusal
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("RUN_LOCAL_SUBAGENTS", "1")
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()

    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        "partial = Path(sys.argv[2])\n"
        "partial.write_text('## PASS\\nno findings\\n\\nTOTAL=0 BLOCKING=0\\n', "
        "encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REVIEW_RUNNER", str(fake_runner))
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path)])
    assert rc == 0

    reports_dir = project_root / ".klc" / "reports"
    reports = sorted(reports_dir.glob("review-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    # KLC-175: layer 1 = code-review, layer 2 only on signal; external on L.
    assert "planned_passes: 2" in text
    assert "executed_passes: 1" in text
    assert "skipped `deep-impact` — no trigger fired" in text
    assert "skipped `security` — no trigger fired" in text
    assert "skipped `drift`" in text


def test_runner_failure_partial_is_not_counted_executed(tmp_path, monkeypatch):
    """D-015: a partial whose first heading is "## Agent run failed —" is
    not an executed pass — it stays planned in the plan, and out of the
    report's executed count."""
    project_root, spec_path = _seed_project(tmp_path, track="L")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("RUN_LOCAL_SUBAGENTS", "1")
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()

    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        "partial = Path(sys.argv[2])\n"
        "if 'code-review' in partial.name:\n"
        "    partial.write_text('## Agent run failed — review-internal\\n\\n"
        "TOTAL=1 BLOCKING=1\\n', encoding='utf-8')\n"
        "else:\n"
        "    partial.write_text('## PASS\\nno findings\\n\\nTOTAL=0 BLOCKING=0\\n', "
        "encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REVIEW_RUNNER", str(fake_runner))
    diff_path = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)

    rc = rv.main(["--diff", str(diff_path), "--spec", str(spec_path)])
    assert rc in (0, 1)

    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990"
                       / "review" / "review-plan-r1.json").read_text(encoding="utf-8"))
    failed = next(p for p in plan["passes"] if p["reviewer"] == "code-review")
    assert failed["status"] == "planned", \
        "a runner-failure partial must not flip the pass to executed"

    reports_dir = project_root / ".klc" / "reports"
    reports = sorted(reports_dir.glob("review-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "executed_passes: 0" in text   # the one code-review failed, external has no summary


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
