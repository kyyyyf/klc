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


def validate_repro(text: str) -> list[str]:
    """Return violation messages for a repro.md; empty list means valid."""
    out = []
    for sec in REPRO_SECTIONS:
        m = re.search(rf"(?m)^##\s+{re.escape(sec)}\s*$", text)
        if not m:
            out.append(f"repro.md: missing section '{sec}'")
            continue
        body = text[m.end():].split("\n##")[0].strip()
        if not body:
            out.append(f"repro.md: section '{sec}' is empty")
    return out


def has_failing_test_ref(repro_text: str, spec_text: str) -> bool:
    """Return True when a FAILING-TEST: marker is present in repro or spec."""
    return bool(_MARKER.search(repro_text) or _MARKER.search(spec_text))
