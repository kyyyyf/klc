#!/usr/bin/env python3
"""tests/integration/test_klc127_headless_findings.py — KLC-127 step-9, AC-14:
the six headless reviewer prompts write a one-shape `findings.json` (with
`id`, without `reviewer`); `scripts/review.py` checks every partial with
`handback.validate_findings("code-review", list)`, leaves an invalid one out
with one note naming the reviewer and its errors, stamps `reviewer`/`kind`,
and appends to `findings.json` when it knows the ticket.

Hermetic: every test works on tmp_path; PROJECT_ROOT is set only where the
test needs ticket resolution, never touching the live `.klc/`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import review as rv  # noqa: E402

HEADLESS_PROMPTS = ("deep-impact", "architecture", "security",
                    "performance", "code-review")
_REVIEWER_KEY_RE = re.compile(r'"reviewer"\s*:')
_ID_KEY_RE = re.compile(r'"id"\s*:')


def _write_findings(partials_dir: Path, reviewer: str, items: list) -> None:
    d = partials_dir / reviewer
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps(items), encoding="utf-8")


def test_scripts_review_checks_each_partial_and_leaves_out_an_invalid_one_with_one_note(
        tmp_path, capsys):
    """AC-14: a valid partial's findings appear; an old-shape partial
    (rule_name present, id absent) is left OUT with one note naming the
    reviewer and its errors, and the run does not abort."""
    partials_dir = tmp_path / "partials"
    _write_findings(partials_dir, "good-reviewer", [
        {"id": "F-1", "rule_name": "readability", "severity": "MEDIUM",
         "file": "f.py", "line": 5, "title": "t", "body": "b", "fix": None},
    ])
    _write_findings(partials_dir, "bad-reviewer", [
        {"rule_name": "readability", "severity": "MEDIUM", "file": "g.py",
         "line": 5, "title": "t2", "body": "b2", "fix": None},  # old shape: no id
    ])

    good = rv._parse_partial(partials_dir / "good-reviewer.partial.md", {})
    bad = rv._parse_partial(partials_dir / "bad-reviewer.partial.md", {})

    assert good["total"] == 1
    assert bad["total"] == 0
    assert bad["issues"] == []
    err = capsys.readouterr().err
    assert "bad-reviewer" in err


def test_a_valid_partial_is_stamped_with_its_reviewer_name_and_kind(tmp_path):
    """AC-14: a valid partial's findings are stamped reviewer=<directory
    name>, kind="code-review" — the headless prompt itself never writes
    either field."""
    partials_dir = tmp_path / "partials"
    _write_findings(partials_dir, "architecture", [
        {"id": "F-1", "rule_name": "public-api-without-adr", "severity": "HIGH",
         "file": "api.py", "line": 12, "title": "t", "body": "b", "fix": None},
    ])
    result = rv._parse_partial(partials_dir / "architecture.partial.md", {})
    assert len(result["issues"]) == 1
    finding = result["issues"][0]["finding"]
    assert finding.reviewer == "architecture"
    assert finding.kind == "code-review"


def test_the_headless_run_appends_to_findings_json_for_a_known_ticket(
        tmp_path, monkeypatch):
    """AC-14/D-111: `_pooled_findings` appends to findings.json
    for a known ticket, so `findings.py pool` counts the headless partials
    among the review kinds."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    partials_dir = tmp_path / "partials"
    _write_findings(partials_dir, "security", [
        {"id": "F-1", "rule_name": "ssrf", "severity": "HIGH", "file": "f.py",
         "line": 1, "title": "t", "body": "b", "fix": None},
    ])

    pooled, notes = rv._pooled_findings(partials_dir, "KLC-991")

    assert len(pooled) == 1
    tdir = project / ".klc" / "tickets" / "KLC-991"
    assert not (tdir / "review" / "headless-findings.json").exists()   # KLC-173
    stored = json.loads((tdir / "findings.json").read_text(encoding="utf-8"))
    assert len(stored) == 1
    assert stored[0]["reviewer"] == "security"
    assert stored[0]["kind"] == "code-review"


@pytest.mark.parametrize("name", HEADLESS_PROMPTS)
def test_headless_reviewer_prompts_specify_a_one_shape_findings_json_with_id(name):
    """AC-14: each of the five headless reviewer prompts names findings.json,
    id, rule_name, title and body, and does not ask for a reviewer field —
    intake stamps it (F-008: architecture/security/performance/test-coverage
    wrote rule_name with no id; deep-impact wrote markdown only — this pins that
    all five now converge)."""
    text = (FW_ROOT / "core" / "agents" / "review" / f"{name}.md").read_text(encoding="utf-8")
    assert "findings.json" in text
    assert _ID_KEY_RE.search(text), f"{name}.md: no \"id\": key in its findings.json schema"
    assert '"rule_name"' in text
    assert '"title"' in text
    assert '"body"' in text
    assert not _REVIEWER_KEY_RE.search(text), \
        f"{name}.md: still asks for a \"reviewer\" field; intake stamps it"
