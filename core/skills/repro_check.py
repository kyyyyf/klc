"""repro_check.py — validate repro.md sections and detect the failing-test marker.

Public API:
    REPRO_SECTIONS: tuple of required section names.
    validate_repro(text) -> list[str]
        Return a list of violation messages; empty means valid.
    has_failing_test_ref(repro_text, spec_text) -> bool
        True when a FAILING-TEST: marker is present in either file.
"""
from __future__ import annotations

import re

REPRO_SECTIONS = ("Problem", "Environment", "Steps", "Expected vs actual")

_MARKER = re.compile(r"(?im)^\s*FAILING-TEST:\s*\S+")
# Strip HTML scaffold comments (<!-- ... -->) before checking section body emptiness.
_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
# Strip bare scaffold-placeholder lines: numbered list items (1.) and label-only lines
# (Expected:, Actual:) with no content following.
_SCAFFOLD_LINE_RE = re.compile(r'(?m)^[ \t]*(?:\d+\.|Expected:|Actual:)[ \t]*$')


def _meaningful_body(raw: str) -> str:
    """Strip HTML comments and bare scaffold lines; return stripped text."""
    s = _COMMENT_RE.sub('', raw)
    s = _SCAFFOLD_LINE_RE.sub('', s)
    return s.strip()


def validate_repro(text: str) -> list[str]:
    """Return violation messages for a repro.md; empty list means valid."""
    out = []
    for sec in REPRO_SECTIONS:
        m = re.search(rf"(?m)^##\s+{re.escape(sec)}\s*$", text)
        if not m:
            out.append(f"repro.md: missing section '{sec}'")
            continue
        raw_body = text[m.end():].split("\n##")[0]
        if not _meaningful_body(raw_body):
            out.append(f"repro.md: section '{sec}' is empty")
    return out


def has_failing_test_ref(repro_text: str, spec_text: str) -> bool:
    """Return True when a real (non-placeholder) FAILING-TEST: marker is present."""
    for text in (repro_text, spec_text):
        m = _MARKER.search(text)
        if m and 'REPLACE' not in m.group(0):
            return True
    return False
