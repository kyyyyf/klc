"""KLC-174 AC-9: prompts, templates, run skill and process.md name the steps.json contract.

The Evidence section, the progress ledger and the removed knobs must not survive
in any agent prompt (source or generated), template, the hand-written run skill
or docs/process.md. tests/fixtures is deliberately not scanned.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GONE = ("## Evidence", "progress.md", "build.verify_steps", "step_ledger", "evidence_gate")


def _files():
    return [
        *ROOT.glob("core/agents/**/*.md"),
        *ROOT.glob("core/templates/**/*"),
        *ROOT.glob("klc-plugin/agents/*.md"),
        ROOT / "klc-plugin/skills/go/SKILL.md",
        ROOT / "docs/process.md",
    ]


def test_removed_evidence_and_ledger_names_do_not_survive():
    bad = []
    for f in _files():
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        bad += [f"{f.relative_to(ROOT)} still names {n}" for n in GONE if n in text]
    assert not bad, "\n".join(bad)


def test_templates_and_docs_point_at_klc_step_verify():
    for rel in ("core/templates/impl-step.md.j2", "core/agents/impl.md",
                "docs/process.md",
                "klc-plugin/skills/go/SKILL.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "klc step verify" in text or "klc step <KEY> verify" in text, rel
    assert "steps.json" in (ROOT / "docs/process.md").read_text(encoding="utf-8")
    brief = (ROOT / "core/templates/task-brief.md.j2").read_text(encoding="utf-8")
    assert "build-log" not in brief
