"""KLC-176 step-5: prompts, plugin run skill and process.md name the new layout.

The artefacts KLC-176 retired must not survive in an agent prompt (source or
generated), the hand-written run skill or docs/process.md. tests/fixtures is not
scanned: frozen dogfood data may name old files.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GONE = re.compile(
    r"options-lite|design/options|design/adr|ADR\.md|manual-checklist|integrate\.md"
    r"|_superseded|(?<!scratch/<KEY>/)retrieval_trace"
)


def _files():
    return [
        *ROOT.glob("core/agents/**/*.md"),
        *ROOT.glob("klc-plugin/agents/*.md"),
        ROOT / "klc-plugin/skills/run/SKILL.md",
        ROOT / "docs/process.md",
    ]


def test_retired_artefact_names_are_gone_from_prompts_and_docs():
    bad = []
    for f in _files():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = GONE.search(line)
            if m:
                bad.append(f"{f.relative_to(ROOT)}:{n} still names {m.group(0)}")
    assert not bad, "\n".join(bad)


def test_process_doc_lists_the_new_ticket_files():
    text = (ROOT / "docs/process.md").read_text(encoding="utf-8")
    for name in ("design.md", "build/steps.json", "findings.json", "advisories.json",
                 "review-plan-r<N>.json", "review-report.md", "retrospective.md"):
        assert name in text, name
    for h in ("What the gates missed", "Token cost by phase", "One process change"):
        assert h in text, h


def test_retrospective_prompt_names_the_three_headings_and_forty_lines():
    text = (ROOT / "core/agents/retrospective.md").read_text(encoding="utf-8")
    for h in ("## What the gates missed", "## Token cost by phase", "## One process change"):
        assert h in text, h
    assert "40 lines" in text
    disc = (ROOT / "core/agents/discovery.md").read_text(encoding="utf-8")
    assert "What the gates missed" in disc and "One process change" in disc
