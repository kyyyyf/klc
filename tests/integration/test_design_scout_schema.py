#!/usr/bin/env python3
"""Integration tests for design-scout prompt schema (KLC-026 step-1 & step-2).

Tests:
- AC-2: scout output has the four required fields (confirmed_files,
  dependency_impact, open_questions, advisory recommended_option_shape)
- AC-2: every file reference carries a verified file:line
- AC-3: scout output contains NO reject/prune/option-killing directive
         (structural enforcement via scout_check)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

# ---------------------------------------------------------------------------
# Fixtures: synthetic scout.md content
# ---------------------------------------------------------------------------

_VALID_SCOUT = """\
---
ticket: KLC-TEST
phase: design
scout_version: 1
---

# Design Scout Analysis

## confirmed_files

- `core/skills/route_heuristic.py:45` — public API: `classify()`
- `core/skills/track_classifier.py:12` — affected symbol: `final_track()`

## dependency_impact

- `core/skills/phase_completion.py:124` — imports `route_heuristic.classify`;
  must remain compatible if `classify()` signature changes.
- No external dependents beyond affected_set.

## open_questions

- Does `classify()` have callers outside core/skills/? LSP findReferences shows
  no callers in tests/; confirmed via `scripts/review.py:289`.

## recommended_option_shape

ADVISORY: Option A can use the existing `_track_max` helper; Option B may
benefit from extracting the axis-override logic into `track_classifier.py:15`
for easier testing. This is advisory only — all three options remain viable.
"""

_SCOUT_WITH_REJECT = """\
---
ticket: KLC-TEST
---

## confirmed_files

- `core/module.py:10`

## dependency_impact

- `tests/test_module.py:5` — no impact

## open_questions

None.

## recommended_option_shape

ADVISORY: Option C is not viable because it requires too many changes.
REJECT Option A — it contradicts the ADR.
"""

_SCOUT_MISSING_FIELDS = """\
---
ticket: KLC-TEST
---

## confirmed_files

- `core/module.py:10`

## open_questions

Missing dependency_impact and recommended_option_shape.
"""

_SCOUT_NO_FILE_LINES = """\
---
ticket: KLC-TEST
---

## confirmed_files

- `core/module.py` — no line number!

## dependency_impact

- `tests/test_x.py` — also missing line number

## open_questions

None.

## recommended_option_shape

ADVISORY: all options viable.
"""

# Regex for file:line (e.g. `path/to/file.py:42`)
_FILE_LINE_RE = re.compile(r"`[^`]+\.[a-zA-Z]{1,6}:\d+`")
# Sections that must appear
_REQUIRED_SECTIONS = [
    "confirmed_files",
    "dependency_impact",
    "open_questions",
    "recommended_option_shape",
]
# Option-killing directives that must NOT appear
_REJECT_PATTERNS = [
    re.compile(r"\bREJECT\b", re.IGNORECASE),
    re.compile(r"\bprune\b.*option", re.IGNORECASE),
    re.compile(r"option\s+[ABC]\s+is\s+not\s+viable", re.IGNORECASE),
    re.compile(r"kill\s+option", re.IGNORECASE),
]


def _has_all_sections(text: str) -> list[str]:
    """Return list of missing required section headings."""
    missing = []
    for section in _REQUIRED_SECTIONS:
        # Section headings: ## section_name or ## Section Name
        if not re.search(rf"^##\s+{re.escape(section)}", text, re.MULTILINE | re.IGNORECASE):
            missing.append(section)
    return missing


def _extract_file_refs(text: str) -> list[str]:
    """Return all backtick-quoted file references in the text."""
    return re.findall(r"`([^`]+\.[a-zA-Z]{1,6}[^`]*)`", text)


def _has_reject_directive(text: str) -> list[str]:
    """Return matched reject/prune directives found in text."""
    hits = []
    for pat in _REJECT_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append(m.group(0))
    return hits


# ---------------------------------------------------------------------------
# AC-2: structured fields present
# ---------------------------------------------------------------------------

def test_structured_fields_present():
    """Valid scout.md has all four required section headings."""
    missing = _has_all_sections(_VALID_SCOUT)
    assert not missing, f"missing sections in valid scout: {missing}"


def test_structured_fields_missing_detected():
    """Scout.md with missing fields is correctly detected as invalid."""
    missing = _has_all_sections(_SCOUT_MISSING_FIELDS)
    assert "dependency_impact" in missing
    assert "recommended_option_shape" in missing


# ---------------------------------------------------------------------------
# AC-2: every file reference has :line
# ---------------------------------------------------------------------------

def test_every_file_ref_has_line():
    """Every file reference in a valid scout.md carries a :line suffix."""
    refs = _extract_file_refs(_VALID_SCOUT)
    assert refs, "no file refs found in scout fixture"
    for ref in refs:
        # A file ref without :line is a plain extension like `.py` with no colon
        if re.search(r"\.[a-zA-Z]{1,6}$", ref) and ":" not in ref:
            assert False, f"file ref missing :line: `{ref}`"


def test_file_ref_without_line_detected():
    """File references without :line are detected."""
    refs = _extract_file_refs(_SCOUT_NO_FILE_LINES)
    no_line = [r for r in refs if re.search(r"\.[a-zA-Z]{1,6}$", r) and ":" not in r]
    assert no_line, "expected to detect refs without :line"


# ---------------------------------------------------------------------------
# AC-3: no reject directive (step-1 prose check)
# ---------------------------------------------------------------------------

def test_no_reject_directive():
    """Valid scout.md has no reject/prune/option-killing directive."""
    hits = _has_reject_directive(_VALID_SCOUT)
    assert not hits, f"unexpected reject directive in valid scout: {hits}"


def test_reject_directive_detected():
    """Scout.md with a REJECT directive is caught by the checker."""
    hits = _has_reject_directive(_SCOUT_WITH_REJECT)
    assert hits, "expected reject directive to be detected"


# ---------------------------------------------------------------------------
# AC-3 (step-2): structural checker (scout_check.py)
# ---------------------------------------------------------------------------

def test_scout_check_valid_passes():
    """scout_check.check() returns (True, []) for a valid scout.md."""
    import scout_check as sc
    ok, errors = sc.check(_VALID_SCOUT)
    assert ok, f"expected ok=True for valid scout, got errors: {errors}"
    assert errors == []


def test_scout_check_reject_fails():
    """scout_check.check() returns (False, [msg]) when reject directive present."""
    import scout_check as sc
    ok, errors = sc.check(_SCOUT_WITH_REJECT)
    assert not ok, "expected ok=False for scout with REJECT directive"
    assert errors, "expected at least one error message"


def test_scout_check_missing_fields_fails():
    """scout_check.check() returns (False, [msg]) when required fields missing."""
    import scout_check as sc
    ok, errors = sc.check(_SCOUT_MISSING_FIELDS)
    assert not ok, "expected ok=False for scout with missing fields"
    assert errors


def test_prompt_file_exists():
    """core/agents/design-scout.md must exist with the required sections."""
    prompt_path = FW_ROOT / "core" / "agents" / "design-scout.md"
    assert prompt_path.exists(), f"design-scout.md missing at {prompt_path}"
    text = prompt_path.read_text(encoding="utf-8")
    assert "## Role" in text
    assert "confirmed_files" in text
    assert "dependency_impact" in text
    assert "open_questions" in text
    assert "recommended_option_shape" in text
    assert "advisory" in text.lower() or "ADVISORY" in text
    # Must explicitly say reject/prune is not allowed
    assert "reject" in text.lower() or "prune" in text.lower() or "no option-killing" in text.lower()
