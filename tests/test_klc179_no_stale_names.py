"""KLC-179 step-5: the retired phase names are gone from live prompts, skills,
config and the process doc (docs/process.md keeps ONE "retired phases" sentence)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STALE = re.compile(r"xs-build|review-lite|detailed-test-plan|xs-fasttrack|force-xs-skip")


def _files():
    out = [p for p in (ROOT / "core" / "agents").rglob("*") if p.is_file()]
    out += [p for p in (ROOT / "klc-plugin" / "skills").rglob("*") if p.is_file()]
    out += list((ROOT / "config").glob("*.yml"))
    return out


def test_no_stale_phase_names_in_prompts_skills_config():
    bad = {str(p.relative_to(ROOT)): sorted(set(STALE.findall(p.read_text("utf-8"))))
           for p in _files() if STALE.search(p.read_text("utf-8"))}
    assert not bad, bad


def test_process_doc_names_retired_phases_in_one_sentence_only():
    lines = [ln for ln in (ROOT / "docs" / "process.md").read_text("utf-8").splitlines()
             if STALE.search(ln)]
    assert len(lines) <= 1, lines
    assert not lines or "retired" in lines[0].lower()


def test_process_doc_describes_the_facts_model():
    text = (ROOT / "docs" / "process.md").read_text("utf-8")
    for needle in ("spec_approved", "steps_green", "light", "full", "klc fix track",
                   "prompt table", "KLC-140"):
        assert needle in text, needle
