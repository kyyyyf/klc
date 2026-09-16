#!/usr/bin/env python3
"""tests/test_klc113_step_parser.py — KLC-113 step-6: one impl-plan step parser.

AC-11: `core/skills/artefacts.py` uses `impl_plan_check.parse_impl_plan_steps`
plus the shared field extractor; `_extract_impl_step` is deleted and no regex
matching the legacy `**Affected files**` / `**Expected tests**` spellings
remains anywhere in `core/skills/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW))

import artefacts  # noqa: E402


def test_extract_impl_step_removed_from_artefacts() -> None:
    assert not hasattr(artefacts, "_extract_impl_step"), (
        "artefacts._extract_impl_step must be deleted (AC-11) — "
        "write_step_card now uses impl_plan_check.parse_impl_plan_steps "
        "plus the shared extract_step_fields"
    )


def test_no_legacy_field_regex_in_core_skills() -> None:
    hits = []
    for py in sorted((FW / "core" / "skills").glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for legacy in ("**Affected files**", "**Expected tests**"):
            if legacy in text:
                hits.append(f"{py.name}: {legacy}")
    assert hits == [], hits
