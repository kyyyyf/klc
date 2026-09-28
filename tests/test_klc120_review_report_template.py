#!/usr/bin/env python3
"""KLC-120 step-4 — AC-7: core/templates/review-report.md.j2 renders the
planned/executed/skipped/override fields (confirms the in-client path,
which renders through the same template, gets the same fields); a caller
that doesn't pass any of the new variables still renders under
StrictUndefined (every new variable is behind a `default` filter)."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

FW_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = FW_ROOT / "core" / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


_BASE_KWARGS = dict(
    timestamp="2026-09-28T00:00:00Z",
    spec_path="/tmp/spec.md",
    reviewers=[],
    external=None,
    blocking_issues="_None._",
    non_blocking_issues="_None._",
    out_of_scope_issues="_None._",
    verdict="APPROVED",
    adrs=[],
    tier_classification={},
    sentinel_matches={},
)


def test_review_report_template_renders_planned_executed_skipped_and_override_fields():
    """AC-7 (acceptance row): the template renders planned_passes,
    executed_passes, every skipped pass with its reason, and cap_override
    with the cap value when set."""
    tpl = _env().get_template("review-report.md.j2")
    text = tpl.render(
        **_BASE_KWARGS,
        planned_passes=5,
        executed_passes=4,
        skipped_passes=[
            {"reviewer": "deep-impact", "skip_reason": "no trigger fired"},
            {"reviewer": "code-review", "skip_reason": "in-client pass"},
        ],
        cap=4,
        cap_override=True,
    )
    assert "planned_passes: 5" in text
    assert "executed_passes: 4" in text
    assert "cap_override: true" in text
    assert "cap: 4" in text
    assert "skipped `deep-impact` — no trigger fired" in text
    assert "skipped `code-review` — in-client pass" in text
    assert "per-step build review: not counted" in text


def test_template_renders_without_pass_fields_for_legacy_callers():
    """A caller that passes none of the new KLC-120 variables (a legacy
    render site) still renders under StrictUndefined — every new variable
    sits behind a `default` filter."""
    tpl = _env().get_template("review-report.md.j2")
    text = tpl.render(**_BASE_KWARGS)
    assert "planned_passes: n/a" in text
    assert "executed_passes: n/a" in text
    assert "cap_override: true" not in text


if __name__ == "__main__":
    import pytest
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
