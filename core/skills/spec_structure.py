"""Structural helpers for spec.md analysis (approach detection, pick recording)."""
from __future__ import annotations

import re

_APPROACH_LABEL_RE = re.compile(
    r"(?im)^\s*(?:[-*]|\d+\.|#{2,3})\s*((?:option|approach|alternative)\s*[a-z0-9]*)\b",
)

_PICKED_RE = re.compile(r"\bPicked:")
_DECISION_RE = re.compile(r"\bDECISION\s+D-\d+\b")


def has_min_approaches(text: str, n: int = 2) -> bool:
    """True iff the text proposes >= n distinct approaches.

    De-duplicates by normalized label (keyword + trailing identifier), not
    by full line — so 'Option A: foo' and 'Option A: bar' count as one.
    """
    matches = _APPROACH_LABEL_RE.findall(text)
    normalized = {m.strip().lower() for m in matches}
    return len(normalized) >= n


def recorded_pick(text: str) -> bool:
    """True iff text contains a recorded pick marker (Picked: or DECISION D-NNN)."""
    return bool(_PICKED_RE.search(text) or _DECISION_RE.search(text))
