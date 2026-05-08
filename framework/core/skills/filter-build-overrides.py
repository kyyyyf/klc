#!/usr/bin/env python3
"""filter-build-overrides.py — strip Build.cs-only override modules from
modules.json and move them into a separate `build_overrides` section.

An "override" is a module that:
  - reports zero source symbols (symbol_count == 0), AND
  - its path is a prefix or suffix of another same-language module's path
    (i.e. it shares a directory tree with a real code module).

In UE projects this idiom is used to hijack engine plugin rules — the
local `NetcodeUnitTest.Build.cs` forces bUsePrecompiled=false without adding
any C++ of its own. Leaving such entries in `modules[]` causes spurious
module-path collisions during docgen and inflates module counts.

Usage:
    filter-build-overrides.py [--in framework/index/modules.json]
                              [--out framework/index/modules.json]

The script reads JSON, rewrites it in place (or to --out), and prints a
one-line summary to stdout: "filter-build-overrides: moved N module(s)".
Exit 0 even if nothing was moved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="src", default="framework/index/modules.json")
    ap.add_argument("--out", dest="dst", default=None)
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst) if args.dst else src
    if not src.exists():
        sys.stderr.write(f"filter-build-overrides: input {src} not found\n")
        return 1

    data = json.loads(src.read_text(encoding="utf-8"))
    modules = data.get("modules", [])
    overrides = data.get("build_overrides", [])

    # For each same-language pair of modules, check whether their paths share
    # a directory tree (identical, prefix, or suffix). A zero-symbol module
    # that shares a tree with a real one is treated as a Build.cs-only override.
    by_lang: dict[str, list[dict]] = {}
    for m in modules:
        by_lang.setdefault(m.get("language", ""), []).append(m)

    moved = []
    kept: list[dict] = []
    for m in modules:
        if m.get("symbol_count", 0) != 0:
            kept.append(m)
            continue
        lang = m.get("language", "")
        my_name = m.get("name", "")
        my_path = m.get("path", "")
        shares_tree = False
        for other in by_lang.get(lang, []):
            if other.get("name") == my_name:
                continue
            op = other.get("path", "")
            if op and (op == my_path or op.startswith(my_path) or my_path.startswith(op)):
                shares_tree = True
                break
        if shares_tree:
            moved.append(m)
        else:
            kept.append(m)

    if moved:
        # Drop edges pointing into the moved modules from the kept set, so the
        # dependency graph stays consistent with modules[].
        names_moved = {m["name"] for m in moved}
        for m in kept:
            m["depends_on"]  = [x for x in m.get("depends_on", [])  if x not in names_moved]
            m["depended_by"] = [x for x in m.get("depended_by", []) if x not in names_moved]
        data["modules"] = kept
        data["build_overrides"] = overrides + moved
        data.setdefault("notes", []).append(
            f"filter-build-overrides: moved {len(moved)} zero-symbol module(s) "
            f"sharing a path with a real code module into build_overrides[]: "
            f"{sorted(names_moved)}."
        )

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"filter-build-overrides: moved {len(moved)} module(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
