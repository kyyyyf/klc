#!/usr/bin/env python3
"""diff-modules.py — given a unified diff, print the set of module
names whose path is the longest matching prefix for any file touched
by the diff.

Usage:
    diff-modules.py <diff.patch>                  # reads modules.json from default path
    diff-modules.py <diff.patch> --modules <path> # explicit modules.json

Output: one module name per line on stdout, sorted, deduped. Exit 0.

Why a dedicated skill: bash `grep -F` matches substrings, so a diff
touching `MyProject/Source/MyProjectTests/...` would also match the
module rooted at `MyProject/Source/MyProject/` — a false positive.
Longest-prefix resolution fixes it and is the same logic the decompose
agent uses when assigning symbols to modules.

Preconditions:
- Diff paths (the `+++ b/<path>` / `--- a/<path>` headers) MUST be
  relative to the project root — same root that `modules.json:path`
  entries are relative to. `git diff HEAD` from the project root
  produces this shape by default. When callers stitch a diff from a
  different CWD they must strip or rewrite the prefix first; this skill
  does not auto-detect the root.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))  # so `import module_membership` resolves
from core.shared.paths import framework_root, klc_index_dir  # noqa: E402, F401
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)


def parse_diff_files(diff_path: Path) -> list[str]:
    """Return paths listed in `+++ b/<path>` (or `--- a/<path>` when the
    file is deleted, for completeness)."""
    files: set[str] = set()
    try:
        text = diff_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    for line in text.splitlines():
        if line.startswith("+++ b/") and not line.startswith("+++ b//dev/null"):
            files.add(line[6:].strip())
        elif line.startswith("+++ /dev/null"):
            continue
        elif line.startswith("--- a/"):
            files.add(line[6:].strip())
    # Drop /dev/null artefacts and empty entries.
    return sorted(p for p in files if p and p != "/dev/null")


def affected_modules(diff_path: Path, modules_data: dict) -> list[str]:
    """Modules touched by the diff. KLC-066: routes through the single
    file_to_module() resolver (private longest-prefix copy deleted). Accepts the
    full modules.json object so `files` overrides are honoured. A shared file
    contributes every module in its member_of so it is not stranded.

    A bare list is accepted too (wrapped) for back-compat."""
    if isinstance(modules_data, list):
        modules_data = {"modules": modules_data}
    files = parse_diff_files(diff_path)
    names: set[str] = set()
    for f in files:
        names.update(_mm.file_to_module(f, modules_data)["member_of"])
    return sorted(names)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("diff", type=Path)
    ap.add_argument("--modules", type=Path,
                    default=klc_index_dir() / "modules.json")
    args = ap.parse_args()

    if not args.diff.exists():
        sys.stderr.write(f"diff-modules: diff {args.diff} not found\n")
        return 1
    if not args.modules.exists():
        sys.stderr.write(f"diff-modules: modules.json {args.modules} not found\n")
        return 1

    modules_data = json.loads(args.modules.read_text(encoding="utf-8"))
    if not isinstance(modules_data, dict):
        modules_data = {"modules": modules_data}
    for name in affected_modules(args.diff, modules_data):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
