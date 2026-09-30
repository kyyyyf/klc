#!/usr/bin/env python3
"""tests/integration/test_klc127_report_render.py — KLC-127 step-9, AC-22:
`scripts/review.py` renders the report findings from `findings.aggregate`,
then `dedupe`, then `sort_for_report`, in that order (F-001: the three
functions were imported and never called) — one defect independently
reported by several headless reviewers renders once, and a legacy
markdown-only partial (predating the findings.json convention) still
renders.

Hermetic: every test works on tmp_path; no PROJECT_ROOT/CLI/subprocess/git.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import review as rv  # noqa: E402


def _write_findings(partials_dir: Path, reviewer: str, items: list) -> None:
    d = partials_dir / reviewer
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps(items), encoding="utf-8")


def test_headless_report_renders_findings_through_aggregate_dedupe_sort_for_report_in_order(
        tmp_path, monkeypatch):
    """AC-22: `_pooled_findings` calls aggregate, then dedupe, then
    sort_for_report, in that exact order — closing F-001's gap for real."""
    calls: list[str] = []
    orig_aggregate, orig_dedupe, orig_sort = rv.aggregate, rv.dedupe, rv.sort_for_report

    def _spy_aggregate(*a, **k):
        calls.append("aggregate")
        return orig_aggregate(*a, **k)

    def _spy_dedupe(*a, **k):
        calls.append("dedupe")
        return orig_dedupe(*a, **k)

    def _spy_sort(*a, **k):
        calls.append("sort_for_report")
        return orig_sort(*a, **k)

    monkeypatch.setattr(rv, "aggregate", _spy_aggregate)
    monkeypatch.setattr(rv, "dedupe", _spy_dedupe)
    monkeypatch.setattr(rv, "sort_for_report", _spy_sort)

    partials_dir = tmp_path / "partials"
    _write_findings(partials_dir, "r1", [
        {"id": "F-1", "rule_name": "readability", "severity": "LOW",
         "file": "f.py", "line": 1, "title": "t", "body": "b", "fix": None},
    ])

    rv._pooled_findings(partials_dir, None)

    assert calls == ["aggregate", "dedupe", "sort_for_report"]


def test_one_defect_from_three_reviewers_renders_once(tmp_path):
    """AC-22: one defect independently reported by THREE reviewers (same
    file, high-similarity title/body, different reviewer) renders exactly
    once in the report, not three times."""
    partials_dir = tmp_path / "partials"
    shared_body = "modelusage cumulative tokens accounting basis session drift here"
    for reviewer in ("architecture", "security", "performance"):
        _write_findings(partials_dir, reviewer, [
            {"id": "F-1", "rule_name": "readability", "severity": "HIGH",
             "file": "runner.py", "line": 88, "title": "mixes accounting bases",
             "body": shared_body, "fix": None},
        ])

    pooled, notes = rv._pooled_findings(partials_dir, None)
    assert len(pooled) == 1
    diff_scope = {"runner.py": {"new": {88}, "old": set()}}
    blocking, non_blocking, oos = rv._issue_buckets({}, pooled, diff_scope)
    assert blocking.count("mixes accounting bases") == 1


def test_legacy_markdown_partial_issues_still_render(tmp_path):
    """AC-22 (pin): a legacy markdown-only partial (no findings.json at all,
    predating the convention) still renders through reviewers_data,
    unaffected by the JSON pooling pipeline."""
    partials_dir = tmp_path / "partials"
    partials_dir.mkdir(parents=True)
    md_path = partials_dir / "legacy-reviewer.partial.md"
    md_path.write_text(
        "## Legacy Review\n\n"
        "### [HIGH] An old-style markdown finding\n"
        "**Issue**: something.\n\n"
        "ISSUES_TOTAL=1 ISSUES_BLOCKING=1\n",
        encoding="utf-8",
    )
    result = rv._parse_partial(md_path, {})
    assert result["total"] == 1
    reviewers_data = {"legacy-reviewer": result}

    blocking, non_blocking, oos = rv._issue_buckets(reviewers_data, [], {})
    assert "An old-style markdown finding" in blocking
