"""KLC-175 step-5: the agent prompts, the run skill and the process doc no longer
name the pieces the cascade removed (the rule catalog, the CLAUDE.md bundle, the
cheap-pass agent, the test-coverage reviewer file), and they say what replaced them."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STALE = ("rule_catalog", "claude_md_context", "cascade-cheap", "test-coverage.md")


def _files() -> list[Path]:
    out = sorted((REPO / "core" / "agents").rglob("*.md"))
    return out + [REPO / "klc-plugin" / "skills" / "go" / "SKILL.md",
                  REPO / "docs" / "process.md"]


def test_no_stale_terms_in_prompts_run_skill_and_process_doc():
    hits = [(str(p.relative_to(REPO)), t) for p in _files()
            for t in STALE if t in p.read_text(encoding="utf-8")]
    assert hits == []


def test_review_docs_name_layers_fail_closed_and_headless_cost():
    for rel in ("core/agents/review.md", "docs/process.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "layer" in text.lower(), rel
        assert "--over-cap" in text, rel
        assert "context.md" in text, rel
    review = (REPO / "core/agents/review.md").read_text(encoding="utf-8")
    assert "Run full multi-agent review instead?" not in review   # cheap pass is gone
    run = (REPO / "klc-plugin/skills/go/SKILL.md").read_text(encoding="utf-8")
    assert "--diff recorded" in run and "layer" in run.lower()
