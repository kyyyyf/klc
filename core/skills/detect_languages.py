#!/usr/bin/env python3
"""detect_languages.py — detect project languages from inventory.

Reads:
- .klc/index/inventory.json (file counts per extension)

Returns set of detected languages (python, cpp, typescript, javascript, rust).

Threshold: language detected if ≥10 files of that extension.
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


# Extension to language mapping
EXT_TO_LANG = {
    ".py": "python",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",  # Assuming C++ (could be C, but klc targets C++)
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
}

# Threshold for auto-detection
FILE_COUNT_THRESHOLD = 10


def detect() -> Set[str]:
    """Detect project languages from inventory.json.

    Returns:
        Set of language names (python, cpp, typescript, javascript, rust)
    """
    languages: Set[str] = set()

    inventory_path = klc_index_dir() / "inventory.json"
    if inventory_path.exists():
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            extensions = inventory.get("extensions", {})

            lang_counts: dict[str, int] = {}
            for ext, count in extensions.items():
                lang = EXT_TO_LANG.get(ext)
                if lang:
                    lang_counts[lang] = lang_counts.get(lang, 0) + count

            for lang, count in lang_counts.items():
                if count >= FILE_COUNT_THRESHOLD:
                    languages.add(lang)

        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
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
