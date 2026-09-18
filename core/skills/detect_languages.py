#!/usr/bin/env python3
"""detect_languages.py — detect project languages from structural.json
(KLC-103 D-102).

Reads:
- .klc/index/structural.json (per-language file counts — the FILE universe;
  structural.json is the file universe, inventory.json is the symbol
  universe). The retired read of inventory["extensions"] targeted a key no
  producer ever wrote, so this function silently returned an empty set on
  every project before KLC-103 (AC-10).

Returns set of detected languages (whatever structural.json's `languages` key
lists, at or above FILE_COUNT_THRESHOLD).

Threshold: language detected if >=10 files of that language.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Set

# Add _paths to sys.path if not already
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))

try:
    from _paths import klc_index_dir
except ImportError:
    def klc_index_dir():
        return Path(".klc/index")


# Threshold for auto-detection
FILE_COUNT_THRESHOLD = 10


def detect() -> Set[str]:
    """Detect project languages from structural.json.

    Returns:
        Set of language names structural.json's `languages` key lists with
        >=FILE_COUNT_THRESHOLD files.
    """
    languages: Set[str] = set()

    structural_path = klc_index_dir() / "structural.json"
    if structural_path.exists():
        try:
            structural = json.loads(structural_path.read_text(encoding="utf-8"))
            for lang, stats in (structural.get("languages") or {}).items():
                if int((stats or {}).get("files", 0)) >= FILE_COUNT_THRESHOLD:
                    languages.add(lang)
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError):
            pass

    return languages


def main(argv: list[str]) -> int:
    """CLI entry point."""
    languages = detect()
    if languages:
        print(" ".join(sorted(languages)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
