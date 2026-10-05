"""KLC-175 round 2: the auto gate parses the inline `## Verdict: X` line;
review-cheap is retired from models.yml; review prompts cite one rubric label."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import gate_policy  # noqa: E402


def _report(tmp_path, monkeypatch, body: str) -> str:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-991"
    tdir.mkdir(parents=True)
    (tdir / "review-report.md").write_text(body, encoding="utf-8")
    return gate_policy._read_verdict("KLC-991")


@pytest.mark.parametrize("body,expected", [
    ("# R\n\n## Verdict\nAPPROVED\n\n## Findings\nnone\n", "APPROVED"),
    ("# R\n\n## Verdict\nCHANGES_REQUESTED\n", "CHANGES_REQUESTED"),
    ("# R\n\n## Verdict: APPROVED\n\n## Findings\nnone\n", "APPROVED"),
    ("# R\n\n## Verdict: CHANGES_REQUESTED\n\n## Findings\nx\n", "CHANGES_REQUESTED"),
    ("# R\n\n## Verdict: CHANGES REQUESTED\n", "CHANGES_REQUESTED"),
    ("# R\n\n## Findings\nnone\n", "NO_VERDICT_SECTION"),
])
def test_read_verdict_accepts_block_and_inline_forms(tmp_path, monkeypatch, body, expected):
    assert _report(tmp_path, monkeypatch, body) == expected


def test_models_yml_has_no_review_cheap_rows():
    # Plain text scan: `import yaml` is order-dependent in this suite (another
    # test may put core/shared on sys.path first, shadowing PyYAML — KLC-144).
    text = (FW_ROOT / "config" / "models.yml").read_text(encoding="utf-8")
    live = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("review-cheap" in ln for ln in live)


def test_review_prompts_cite_rubric_by_path_not_by_label():
    text = (FW_ROOT / "core" / "agents" / "review" / "code-review.md").read_text(encoding="utf-8")
    assert "Cite `severity_rubric` by path" not in text
    assert "Cite `config/severity-rubric.md` by path" in text
