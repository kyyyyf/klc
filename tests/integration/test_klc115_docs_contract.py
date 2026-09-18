"""KLC-115 step-8: the per-AC Evidence entry shape, the unverified state and
the graduated FACT-source rule are documented where an agent and an operator
read the build contract (AC-20).
"""
from __future__ import annotations

from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (FRAMEWORK_ROOT / rel).read_text(encoding="utf-8")


def test_impl_prompts_and_process_doc_describe_evidence_shape_and_unverified_state():
    for rel in ("core/agents/impl.md", "klc-plugin/agents/impl.md"):
        text = _read(rel)
        assert "verdict:" in text, f"{rel} must describe the verdict line"
        assert "unverified" in text, f"{rel} must describe the unverified state"
        assert "ONE entry per acceptance criterion" in " ".join(text.split()), (
            f"{rel} must describe one Evidence entry per acceptance criterion")

    process = _read("docs/process.md")
    assert "ONE entry per acceptance criterion" in " ".join(process.split()), (
        "docs/process.md must describe one Evidence entry per acceptance criterion")
    assert "unverified" in process
    assert "verify.entry_budget_seconds" in process


def test_process_doc_describes_the_graduated_fact_source_rule():
    process = _read("docs/process.md")
    assert "FACT_SOURCE_RULE_EPOCH" in process
    assert "evidence=read" in process
    assert "warned" in process.lower()
