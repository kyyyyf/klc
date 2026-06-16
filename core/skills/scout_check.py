"""scout_check.py — structural validator for design/scout.md (KLC-026).

Checks that a scout.md output:
1. Contains all four required section headings.
2. Contains no option-killing directive (REJECT, prune, "not viable", etc.).

Usage:
    from scout_check import check
    ok, errors = check(text)

    # CLI:
    python3 scout_check.py design/scout.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REQUIRED_SECTIONS = [
    "confirmed_files",
    "dependency_impact",
    "open_questions",
    "recommended_option_shape",
]

_REJECT_PATTERNS = [
    re.compile(r"\bREJECT\b"),
    re.compile(r"\bprune\b.*option", re.IGNORECASE),
    re.compile(r"option\s+[ABC]\s+is\s+not\s+viable", re.IGNORECASE),
    re.compile(r"\bkill\s+option\b", re.IGNORECASE),
]


def check(text: str) -> tuple[bool, list[str]]:
    """Return (ok, errors) for the given scout.md text.

    ok=True means the scout is structurally valid (required sections
    present, no option-killing directives).
    """
    errors: list[str] = []

    # 1. Required sections
    for section in _REQUIRED_SECTIONS:
        if not re.search(
            rf"^##\s+{re.escape(section)}", text, re.MULTILINE | re.IGNORECASE
        ):
            errors.append(f"missing required section: {section!r}")

    # 2. Option-killing directives
    for pat in _REJECT_PATTERNS:
        m = pat.search(text)
        if m:
            errors.append(
                f"option-killing directive found: {m.group(0)!r} "
                f"(AC-3: the scout must never reject an option)"
            )

    return (len(errors) == 0), errors


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("usage: scout_check.py <scout.md>\n")
        return 2
    path = Path(argv[0])
    if not path.exists():
        sys.stderr.write(f"scout_check: file not found: {path}\n")
        return 2
    text = path.read_text(encoding="utf-8")
    ok, errors = check(text)
    if ok:
        print(f"scout_check: OK ({path})")
        return 0
    for err in errors:
        sys.stderr.write(f"scout_check: ERROR: {err}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
