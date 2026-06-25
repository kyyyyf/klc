"""Structural helpers for spec.md analysis (approach detection, pick recording)."""
from __future__ import annotations

import re

_APPROACH_LABEL_RE = re.compile(
    r"(?im)^\s*(?:[-*]|\d+\.|#{2,3})\s*((?:option|approach|alternative)\s*[a-z0-9]*)\b",
)

_PICK_LINE_RE = re.compile(r"(?im)^\s*Picked:\s*(.*?)\s*$")
_DECISION_RE = re.compile(r"\bDECISION\s+D-\d+\b")
_PLACEHOLDER_RE = re.compile(r"^(?:<[^>]*>|tbd)$", re.IGNORECASE)
_DECOMPOSE_RE = re.compile(r"\bDISCOVERY_DECOMPOSE\b")
_UPGRADE_M_RE = re.compile(r"\bDISCOVERY_LITE_UPGRADE_M\b")


def has_min_approaches(text: str, n: int = 2) -> bool:
    """True iff the text proposes >= n distinct approaches.

    De-duplicates by normalized label (keyword + trailing identifier), not
    by full line — so 'Option A: foo' and 'Option A: bar' count as one.
    """
    matches = _APPROACH_LABEL_RE.findall(text)
    normalized = {m.strip().lower() for m in matches}
    return len(normalized) >= n


def recorded_pick(text: str) -> bool:
    """True iff text contains a concrete pick (Picked: <non-placeholder>) or DECISION D-NNN.

    Rejects empty, angle-bracket placeholders, and TBD markers.
    """
    if _DECISION_RE.search(text):
        return True
    m = _PICK_LINE_RE.search(text)
    if not m:
        return False
    val = m.group(1).strip()
    if not val:
        return False
    if _PLACEHOLDER_RE.match(val):
        return False
    return True


def has_decompose_signal(text: str) -> bool:
    """True iff text contains a DISCOVERY_DECOMPOSE signal."""
    return bool(_DECOMPOSE_RE.search(text))


def has_upgrade_m_signal(text: str) -> bool:
    """True iff text contains a DISCOVERY_LITE_UPGRADE_M signal."""
    return bool(_UPGRADE_M_RE.search(text))
