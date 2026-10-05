"""KLC-115 step-8: the graduated FACT-source rule is documented where an operator
reads the build contract (AC-20). The Evidence-entry half was removed by KLC-174.
"""
from __future__ import annotations

from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (FRAMEWORK_ROOT / rel).read_text(encoding="utf-8")


def test_process_doc_describes_the_graduated_fact_source_rule():
    process = _read("docs/process.md")
    assert "FACT_SOURCE_RULE_EPOCH" in process
    assert "evidence=read" in process
    assert "warned" in process.lower()
