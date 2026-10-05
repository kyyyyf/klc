#!/usr/bin/env python3
"""KLC-117 step-6 — AC-14: `/klc:run`'s SKILL.md documents reading the advisory
artifact, not a joined string.
"""
from __future__ import annotations

from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SKILL = FW_ROOT / "klc-plugin" / "skills" / "go" / "SKILL.md"


def test_run_skill_no_longer_documents_string_based_advisory_reading():
    text = SKILL.read_text(encoding="utf-8")
    normalised = " ".join(text.split())  # collapse markdown line-wrap whitespace
    assert "advisories.json" in normalised
    assert "ack-advisories.json" not in normalised
    # KLC-176 trimmed the phase-history notes and KLC-177 rewrote the run skill around
    # `klc go`; advisory detail lives in advisories.json, so the old pin on the
    # "phase-history note" sentence is retired.
    # The orchestrator must not be told to parse the note/summary string for
    # advisory content — it reads the artifact instead.
    assert "parse the advisory string" not in normalised
