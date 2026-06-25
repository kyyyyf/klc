"""No-pre-judgment lint for per-run injected reviewer instruction text.

Scans only injected text assembled at review runtime (allowlist blocks,
per-ticket instructions). Never scan committed core/agents/review/*.md prompts
— those contain legitimate calibration language.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# Imperative pre-judgment directives. \s+ tolerates line breaks.
_PATTERNS = [
    r"do\s+not\s+flag\s+(?:the\s+|this\s+)?\w+",
    r"don'?t\s+flag\b",
    r"treat\s+(?:this|it|the\s+\w+)\s+as\s+(?:minor|trivial)",
    r"treat\s+as\s+(?:minor|trivial)",
    r"mark\s+(?:this|it|the\s+\w+)\s+(?:as\s+)?minor",
    r"ignore\s+(?:the\s+|this\s+)?\w+\s+finding",
    r"ignore\s+(?:this|the)\s+(?:issue|finding|file)\b",
    r"skip\s+(?:the\s+|this\s+)?\w+\s+check",
    r"downgrade\s+(?:it|this|the\s+severity)\b",
]
_RE = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def lint_text(text: str) -> list[dict]:
    """Return [{'phrase': str, 'offset': int}, ...] for each pre-judgment hit."""
    return [{"phrase": m.group(0), "offset": m.start()} for m in _RE.finditer(text)]


def main() -> int:
    ap = argparse.ArgumentParser(description="no-pre-judgment lint")
    ap.add_argument("--file", help="text file to scan; default stdin")
    args = ap.parse_args()
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    hits = lint_text(text)
    print(json.dumps({"violations": hits}, indent=2))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
