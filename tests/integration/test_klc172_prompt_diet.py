"""KLC-172 step-4 (AC-11): producer prompts drop downstream-reviewer prose and
the four reviewer prompts share one two-output-classes include."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

FW = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW))

import plugin_gen as pg  # noqa: E402

AGENTS = FW / "core" / "agents"
PRODUCERS = ("discovery", "discovery-lite", "design", "test-planner")
REVIEWERS = ("spec-reviewer", "test-plan-reviewer", "impl-plan-reviewer", "drift-reviewer")
FORBIDDEN_HEADINGS = (
    "## Independent spec review",
    "## Independent impl-plan review",
    "## Independent coverage review",
)
CEILINGS = {"discovery": 12_000, "design": 12_000, "discovery-lite": 12_000, "test-planner": 9_000}


def test_producer_prompts_drop_downstream_reviewer_sections_and_share_include() -> None:
    for name in PRODUCERS:
        text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
        for heading in FORBIDDEN_HEADINGS:
            assert heading not in text, f"{name}.md still has {heading!r}"
    assert (AGENTS / "_includes" / "two-output-classes.md").is_file()
    for name in REVIEWERS:
        text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
        assert "{{include:two-output-classes}}" in text, name
    for name, ceiling in CEILINGS.items():
        size = len((AGENTS / f"{name}.md").read_bytes())
        assert size <= ceiling, f"{name}.md is {size} B, ceiling {ceiling}"
    committed = FW / "klc-plugin" / "agents"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "agents"
        pg.generate_agents(output_dir=out)
        for gen in sorted(out.glob("*.md")):
            dst = committed / gen.name
            assert dst.exists() and dst.read_bytes() == gen.read_bytes(), gen.name


def test_reviewers_keep_only_their_vocabularies_inline() -> None:
    """KLC-172 review round 1 (F-015): the contract prose lives in the include only."""
    for name in REVIEWERS:
        text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
        assert "## The two output classes" not in text, name
        assert "carries a non-empty `recommended`" not in text, name
        assert "MUST lead with a recommendation" not in text, name
        assert "## Closed vocabularies" in text, name


def test_impl_prompt_and_brief_prose_are_accurate() -> None:
    """F-014: the brief carries Goals + ACs for step 1 only."""
    impl = (AGENTS / "impl.md").read_text(encoding="utf-8")
    assert "The brief contains Goals + ACs," not in impl
    assert "step 1" in impl.split("## Inputs", 1)[1].split("##", 1)[0]
    src = (FW / "core" / "skills" / "task_brief.py").read_text(encoding="utf-8")
    assert "already holds them from step 1" not in src
