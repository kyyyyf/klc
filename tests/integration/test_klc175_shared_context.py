"""KLC-175 step-4 (AC-6, AC-7): one shared `context.md` per review run, short
job cards that point at it, and no root CLAUDE.md / rule_catalog / rubric text
in any card or composed prompt.

The real `review.main` writes the cards (no dispatch); the real runner helpers
turn a card into the headless prompt (`runner._compose_prompt`), so what is
asserted is what a headless reviewer would actually receive."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import models as models_mod  # noqa: E402
import review as rv  # noqa: E402
import runner  # noqa: E402
from test_klc120_review_plan import _seed_project, _stub_claude_on_path, _write_diff  # noqa: E402

ROOT_MARKER = "ROOT-CLAUDE-MD-MARKER-4711"
SPEC = """\
---
ticket: KLC-990
---

## Goals
GOAL-SENTENCE-ONE ships a cheap review.

## Acceptance Criteria
- [ ] AC-1: reviewer · reads · context.md · when run

> [!DECISION D-001] owner=ek
> DECISION-BODY-LINE keep one context file.

## Notes
NOT-IN-CONTEXT-NOTES
"""
TEST_PLAN = """\
## Acceptance coverage

| AC | Type | Test | Notes |
|----|------|------|-------|
| AC-1 | unit | tests/test_x.py::test_row_marker | TABLE-ROW-MARKER |
"""
HOT_DIFF = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
            "@@ -1 +1 @@\n-old\n+x = 1  # perf:hot  DIFF-BODY-MARKER\n")


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "klc175_review_runner", FW_ROOT / "scripts" / "review-runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    project_root, spec = _seed_project(tmp_path, track="S")
    spec.write_text(SPEC, encoding="utf-8")
    (spec.parent / "test-plan.md").write_text(TEST_PLAN, encoding="utf-8")
    (project_root / "CLAUDE.md").write_text(f"# root\n{ROOT_MARKER}\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff = _write_diff(tmp_path, "d.patch", HOT_DIFF)
    assert rv.main(["--diff", str(diff), "--spec", str(spec), "--no-external"]) == 0
    out = capsys.readouterr().out
    cards = sorted(project_root.glob(".klc/reports/pending-*/job-*.md"))
    return project_root, spec, cards, out


def _context_path(project_root: Path) -> Path:
    return project_root / ".klc" / "scratch" / "KLC-990" / "review" / "context.md"


def test_context_written_once_and_referenced_by_every_card(run):
    root, spec, cards, out = run
    ctx = _context_path(root)
    assert ctx.is_file()
    assert len(list(root.rglob("context.md"))) == 1
    text = ctx.read_text(encoding="utf-8")
    for marker in ("DIFF-BODY-MARKER", "GOAL-SENTENCE-ONE", "AC-1: reviewer",
                   "TABLE-ROW-MARKER", "DECISION-BODY-LINE"):
        assert marker in text, marker          # KLC- key gets the test-plan table too
    assert "NOT-IN-CONTEXT-NOTES" not in text
    assert ROOT_MARKER not in text
    names = [c.name for c in cards]
    assert "job-code-review.md" in names and "job-performance.md" in names
    for card in cards:
        body = card.read_text(encoding="utf-8")
        assert str(ctx) in body, card.name
        assert len(body.encode("utf-8")) <= 2048, card.name
    # per-run metric: sum of card bytes plus context.md once
    total = sum(c.stat().st_size for c in cards) + ctx.stat().st_size
    assert f"inlined bytes: {total}" in out
    plan = json.loads(next((root / ".klc/tickets/KLC-990/review").glob("review-plan-r*.json"))
                      .read_text(encoding="utf-8"))
    assert plan["inlined_bytes"] == total


def test_no_card_or_prompt_inlines_root_claude_md(run):
    root, spec, cards, _out = run
    rr = _load_runner()
    ctx_text = _context_path(root).read_text(encoding="utf-8")
    rubric_head = next(l for l in (FW_ROOT / "config/severity-rubric.md")
                       .read_text(encoding="utf-8").splitlines()
                       if len(l) > 40 and not l.startswith("#"))
    assert cards
    for card in cards:
        body = card.read_text(encoding="utf-8")
        assert ROOT_MARKER not in body and "rule_catalog" not in body
        assert "claude_md_context" not in body
        assert "config/severity-rubric.md" in body        # named by path only
        fields = rr._parse_job_card(card)
        prompt_path = FW_ROOT / fields["prompt"]
        inputs = rr._build_inputs(fields)
        assert set(inputs) <= {"context", "adr_context", "addendum"}, inputs
        composed = runner._compose_prompt(prompt_path, inputs)
        # review round 1 (F-005): the card's addendum reaches the headless prompt
        assert "Reviewer: " in composed and "### addendum" in composed
        assert ROOT_MARKER not in composed
        assert "### rule_catalog" not in composed and "### claude_md_context" not in composed
        assert "### severity_rubric" not in composed and rubric_head not in composed
        assert composed.count("DIFF-BODY-MARKER") == 1     # context inlined once, no 2nd diff
        assert composed.count("GOAL-SENTENCE-ONE") == 1
        assert ctx_text in composed


def test_addendum_is_clipped_to_one_kilobyte(tmp_path):
    card = tmp_path / "job-x.md"
    ctx = tmp_path / "context.md"
    ctx.write_text("c", encoding="utf-8")
    allow = tmp_path / "allow.yml"
    allow.write_text("entries: []\n", encoding="utf-8")
    rv._write_job_card(card, reviewer="x", prompt="core/agents/review/x.md",
                       context=ctx, addendum="A" * 5000, partial=tmp_path / "x.partial.md",
                       diff=tmp_path / "d.patch", spec=tmp_path / "spec.md",
                       allowlist=allow, adr_context=None, callgraph_slice=None)
    body = card.read_text(encoding="utf-8")
    assert "A" * 1024 in body and "A" * 1025 not in body
    assert len(body.encode("utf-8")) <= 2048


def test_external_card_has_the_same_shape(tmp_path):
    ctx = tmp_path / "context.md"
    ctx.write_text("c", encoding="utf-8")
    card = tmp_path / "job-external.md"
    rv._write_external_card(card, context=ctx, out=tmp_path / "external.json",
                            provider="anthropic", model="m", addendum="focus: security")
    body = card.read_text(encoding="utf-8")
    assert str(ctx) in body and "claude_md_context" not in body
    assert "focus: security" in body and len(body.encode("utf-8")) <= 2048


def test_runner_inlines_context_once_and_ignores_dropped_labels(tmp_path):
    rr = _load_runner()
    ctx = tmp_path / "context.md"
    ctx.write_text("CTX", encoding="utf-8")
    rubric = tmp_path / "rubric.md"
    rubric.write_text("RUBRIC", encoding="utf-8")
    card = tmp_path / "job-code-review.md"
    card.write_text(
        "# Review sub-agent job: code-review\n\n"
        "Prompt file: core/agents/review/code-review.md\nInputs:\n"
        f"- context:           {ctx}\n- severity_rubric:   {rubric}\n"
        f"- rule_catalog:      {rubric}\n- claude_md_context: {rubric}\n", encoding="utf-8")
    inputs = rr._build_inputs(rr._parse_job_card(card))
    assert inputs == {"context": ctx}


def test_external_template_renders_the_shared_context():
    from jinja2 import Environment, StrictUndefined
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    tpl = env.from_string((FW_ROOT / "core/templates/external-review-prompt.j2")
                          .read_text(encoding="utf-8"))
    out = tpl.render(context="SHARED-CTX", focus_areas=["security"], finding_schema="schema")
    assert "SHARED-CTX" in out and "claude_md_context" not in out
