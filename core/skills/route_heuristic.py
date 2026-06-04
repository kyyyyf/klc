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

    return RouteResult(hint=hint, signals=signals)


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
    print(json.dumps({"hint": result.hint, "signals": result.signals}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
