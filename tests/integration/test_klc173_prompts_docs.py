"""KLC-173 AC-9: prompts, plugin, process.md and the run skill name the one-file layout.

The removed artefact names must not survive in any agent prompt (source or
generated), the hand-written run skill or docs/process.md. tests/fixtures is
deliberately not scanned: frozen dogfood data may name old files.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GONE = (
    "-review-findings.json",
    "code-review-findings.json",
    "external-review-findings.json",
    "headless-findings.json",
    "ack-advisories.json",
    "drift-report.json",
    "review-plan.json",
)


def _files():
    return [
        *ROOT.glob("core/agents/**/*.md"),
        *ROOT.glob("klc-plugin/agents/*.md"),
        ROOT / "klc-plugin/skills/run/SKILL.md",
        ROOT / "docs/process.md",
    ]


def test_prompts_docs_plugin_name_new_layout():
    bad = []
    for f in _files():
        text = f.read_text(encoding="utf-8")
        bad += [f"{f.relative_to(ROOT)} still names {n}" for n in GONE if n in text]
    assert not bad, "\n".join(bad)
    inc = (ROOT / "core/agents/_includes/review-findings-assessment.md").read_text(encoding="utf-8")
    assert "findings.json" in inc
    process = (ROOT / "docs/process.md").read_text(encoding="utf-8")
    assert "advisories.json" in process
    assert "review-plan-r<N>.json" in process
    assert "review-plan-r<N>.json" in (ROOT / "core/agents/review.md").read_text(encoding="utf-8")
    assert "advisories.json" in (ROOT / "klc-plugin/skills/run/SKILL.md").read_text(encoding="utf-8")


def test_architecture_doc_and_review_prompt_are_unambiguous():
    arch = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    assert "-review-findings.json" not in arch
    review = (ROOT / "core/agents/review.md").read_text(encoding="utf-8")
    assert "ticket-level" in review and "partial" in review
