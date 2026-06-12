#!/usr/bin/env python3
"""route_heuristic.py — deterministic track routing for klc intake.

classify(raw_text, kind, modules) -> RouteResult

Signals used (highest-priority wins; downgrades forbidden):
  1. kind       — bug/typo → XS bias; feature/tech with migration/auth
                  keywords → M/L bias
  2. raw length — word count: <30=XS, <100=S, <300=M, else=L
  3. keywords   — XS-keywords push toward XS; M/L-keywords push toward M
  4. modules    — count of module names found in raw text;
                  ≥3 distinct modules → M floor

Aggregation: take the maximum track from all signals (downgrade
forbidden). Result written to meta.json:route_hint and :route_signals.

Also returns a `confidence` ("low"|"medium"|"high"): how much to trust
the hint. Short + no keyword/module signal = "low" (under-specified, not
necessarily simple) — the caller should run a cheap triage or route to
full discovery instead of trusting a small track. Length raises
confidence when long; it never lowers the track.

CLI:
    python core/skills/route_heuristic.py <raw.md>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))

from core.shared.paths import klc_index_dir  # noqa: E402

# Track ordering for max() comparison
_TRACK_ORDER = {"XS": 0, "S": 1, "M": 2, "L": 3}
_TRACKS = ["XS", "S", "M", "L"]


def _track_max(a: str, b: str) -> str:
    return a if _TRACK_ORDER[a] >= _TRACK_ORDER[b] else b


# Keywords that push toward XS (trivial changes)
_XS_KEYWORDS = {
    "typo", "rename", "oneline", "one-line", "one_line",
    "fix typo", "fix-typo", "comment", "whitespace",
}

# Keywords that push toward M or L (complex changes)
_ML_KEYWORDS = {
    "migration", "schema", "auth", "authentication", "authorization",
    "breaking", "breaking-change", "security", "cve", "vulnerability",
    "database", "refactor", "architecture", "cross-module",
    "api-change", "api change", "new-feature", "new feature",
}


@dataclass
class RouteResult:
    hint: str                      # "XS" | "S" | "M" | "L"
    signals: dict[str, str] = field(default_factory=dict)
    # signals: {"kind": "XS", "length": "S", "keywords": "M", "modules": "S"}
    confidence: str = "medium"     # "low" | "medium" | "high"
    # confidence answers "how much do we trust this hint?" — it is NOT a
    # track. A short, under-specified ticket with no keyword/module signal is
    # "low": the hint may be a floor, not the truth. Length raises confidence
    # when long; it never lowers the track (aggregation is max-wins).
    modules_matched: list[str] = field(default_factory=list)
    # module names found verbatim in the raw text (also reusable as mentions).


def _signal_from_kind(kind: str) -> str:
    kind = (kind or "").lower()
    if kind == "bug":
        return "XS"
    if kind in ("feature",):
        return "S"
    return "XS"  # tech/unknown — conservative


def _signal_from_length(word_count: int) -> str:
    if word_count < 30:
        return "XS"
    if word_count < 100:
        return "S"
    if word_count < 300:
        return "M"
    return "L"


def _signal_from_keywords(text: str) -> str:
    lower = text.lower()
    has_ml = any(kw in lower for kw in _ML_KEYWORDS)
    has_xs = any(kw in lower for kw in _XS_KEYWORDS)
    if has_ml:
        return "M"
    if has_xs:
        return "XS"
    return "XS"  # no strong signal — neutral (won't raise)


def _signal_from_modules(text: str, modules: list[dict]) -> str:
    """Count distinct module names mentioned in text."""
    if not modules:
        return "XS"
    lower = text.lower()
    matched = sum(
        1 for m in modules
        if m.get("name", "").lower() in lower
    )
    if matched >= 3:
        return "M"
    if matched >= 1:
        return "S"
    return "XS"


def _matched_modules(text: str, modules: list[dict]) -> list[str]:
    """Module names that appear verbatim in the raw text."""
    if not modules:
        return []
    lower = text.lower()
    return [
        m.get("name", "") for m in modules
        if m.get("name", "") and m.get("name", "").lower() in lower
    ]


def _confidence(word_count: int, has_ml: bool, has_xs: bool,
                modules_matched: int) -> str:
    """How much to trust the hint. Low = under-specified, escalate.

    A short ticket = the human hasn't specified it, NOT that it is simple
    (e.g. "support light theme" is short but cross-cutting). So short + no
    signal at all = low confidence → caller should triage or route to full
    discovery rather than trust a small track.
    """
    # Decisive signals → trust the hint.
    if word_count >= 100:
        return "high"           # human specified it in detail
    if has_ml or modules_matched >= 3:
        return "high"           # explicit complexity / cross-module
    if has_xs and word_count < 30:
        return "high"           # explicit triviality ("fix typo")
    # Short and nothing to latch onto → the dangerous under-specified case.
    if word_count < 30 and not has_ml and not has_xs and modules_matched == 0:
        return "low"
    return "medium"


def _load_modules() -> list[dict]:
    modules_path = klc_index_dir() / "modules.json"
    if not modules_path.exists():
        return []
    try:
        return json.loads(
            modules_path.read_text(encoding="utf-8")
        ).get("modules", [])
    except Exception:
        return []


def classify(raw_text: str, kind: str = "unknown",
             modules: list[dict] | None = None) -> RouteResult:
    """Classify a ticket into XS/S/M/L based on deterministic signals.

    Args:
        raw_text: contents of raw.md (description text)
        kind: ticket kind from meta.json (feature/bug/tech/unknown)
        modules: list of module dicts from modules.json (loaded if None)
    """
    if modules is None:
        modules = _load_modules()

    words = re.findall(r"\w+", raw_text)
    word_count = len(words)

    signals = {
        "kind":     _signal_from_kind(kind),
        "length":   _signal_from_length(word_count),
        "keywords": _signal_from_keywords(raw_text),
        "modules":  _signal_from_modules(raw_text, modules),
    }

    hint = "XS"
    for sig in signals.values():
        hint = _track_max(hint, sig)

    lower = raw_text.lower()
    has_ml = any(kw in lower for kw in _ML_KEYWORDS)
    has_xs = any(kw in lower for kw in _XS_KEYWORDS)
    matched = _matched_modules(raw_text, modules)

    return RouteResult(
        hint=hint,
        signals=signals,
        confidence=_confidence(word_count, has_ml, has_xs, len(matched)),
        modules_matched=matched,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_md", type=Path, help="Path to raw.md")
    ap.add_argument("--kind", default="unknown")
    args = ap.parse_args()

    if not args.raw_md.exists():
        sys.stderr.write(f"route_heuristic: {args.raw_md} not found\n")
        return 1

    text = args.raw_md.read_text(encoding="utf-8")
    result = classify(text, kind=args.kind)
    print(json.dumps({
        "hint":            result.hint,
        "confidence":      result.confidence,
        "signals":         result.signals,
        "modules_matched": result.modules_matched,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
