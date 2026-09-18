#!/usr/bin/env python3
"""KLC-116 step-7 — AC-19: the option template and the process documentation
carry the `evidence` attribute, its three companion rules, and the migration
rule (absence predates this ticket) for a reader looking up the inline item
format."""
from __future__ import annotations

from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]


def test_options_template_documents_evidence_attribute():
    text = (FW_ROOT / "core" / "templates" / "options.md.j2").read_text(encoding="utf-8")
    assert "evidence=" in text
    assert "observed" in text and "read" in text and "assumed" in text


def test_process_doc_documents_companion_rules_and_migration():
    text = (FW_ROOT / "docs" / "process.md").read_text(encoding="utf-8")
    section = text.split("## Inline item format", 1)[1]
    assert "evidence=observed" in section or "evidence=<observed" in section
    assert "if-false" in section          # the `assumed` companion
    assert "src=" in section              # the `read` companion (a resolving <file>:<line>)
    assert "predates" in section          # the migration rule: absence is fine on old items
