#!/usr/bin/env python3
"""planning_validate.py — cross-artifact validation for the planning views
(KLC-066 foundation tier).

Validates the self-consistency of modules.json v2 and its `files` membership map
against the single file_to_module() resolver, so a malformed map is caught at
build time instead of silently mis-routing the scope guard.

Checks (this tier — modules.json + resolver only):
  - every module has a canonical `path` or a non-empty `files` list;
  - module `name`s are unique;
  - every `files` override references only real module names
    (primary_module / secondary_modules / member_of);
  - a shared entry (primary_module=null) has member_of with >= 2 modules
    (otherwise it is a mislabelled single-owner file);
  - the resolver round-trips every `files` entry to the membership it declares;
  - orphans: when an explicit file list is supplied (--in-files-list), files that
    resolve to `orphan` are reported (degrades to "not checked" when absent, since
    the deterministic file listing arrives with the inventory skill in KLC-070).

The eligibility cross-check (shared file <=> eligible_as_primary:false in
file_roles.json) belongs to the KLC-070 views tier and is intentionally NOT done
here — file_roles.json does not exist at this tier.

CLI convention: --in-* / --out-*, PROJECT_ROOT from env, exit 0 ok / exit 2 on a
missing-or-bad required input; degrade-not-fail into errors[] for optional inputs.
Use --strict to exit 1 when warnings are present.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))
from core.shared.paths import klc_index_dir  # noqa: E402
import module_membership as _mm  # noqa: E402


def validate(modules_data: dict, files_list: list[str] | None = None) -> dict:
    """Return {"warnings": [...], "errors": [...], "counts": {...}}."""
    warnings: list[str] = []
    errors: list[str] = []

    modules = modules_data.get("modules", [])
    names = [m.get("name") for m in modules]
    valid_names = set(names)

    # unique names
    seen: set[str] = set()
    for n in names:
        if n in seen:
            warnings.append(f"duplicate module name: {n}")
        seen.add(n)

    # every module identifiable by a path or an explicit files list
    for m in modules:
        if not (m.get("path") or m.get("files")):
            warnings.append(f"module has no path and no files: {m.get('name')}")

    files_map = modules_data.get("files") or {}
    shared_count = 0
    for path, entry in files_map.items():
        if not isinstance(entry, dict):
            warnings.append(f"files entry is not an object: {path}")
            continue
        primary = entry.get("primary_module")
        member = entry.get("member_of") or []
        secondary = entry.get("secondary_modules") or []
        # references must exist
        for ref in ([primary] if primary else []) + list(secondary) + list(member):
            if ref not in valid_names:
                warnings.append(f"files[{path}] references unknown module: {ref}")
        # shared entries need >= 2 members
        if primary is None:
            if len(member) < 2:
                warnings.append(
                    f"files[{path}] has primary_module=null but member_of<2 "
                    f"(mislabelled shared file)")
            else:
                shared_count += 1
        # resolver round-trip: the resolver must agree with the declared shape
        res = _mm.file_to_module(path, modules_data)
        if res["resolution_source"] != "files_override":
            warnings.append(
                f"files[{path}] does not round-trip through the resolver "
                f"(got {res['resolution_source']})")

    orphans: list[str] = []
    if files_list is None:
        errors.append("orphan check skipped: no file list supplied "
                      "(deterministic inventory arrives in KLC-070)")
    else:
        for f in files_list:
            if _mm.file_to_module(f, modules_data)["resolution_source"] == "orphan":
                orphans.append(f)
        if orphans:
            warnings.append(f"orphan files (resolve to no module): {sorted(orphans)}")

    return {
        "warnings": warnings,
        "errors": errors,
        "counts": {
            "modules": len(modules),
            "files_overrides": len(files_map),
            "shared_files": shared_count,
            "orphans": len(orphans),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in-modules", type=Path,
                    default=klc_index_dir() / "modules.json")
    ap.add_argument("--in-files-list", type=Path, default=None,
                    help="optional newline-delimited file list for orphan detection")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when warnings are present")
    args = ap.parse_args(argv)

    if not args.in_modules.exists():
        sys.stderr.write(f"planning-validate: modules.json not found at {args.in_modules}\n")
        return 2
    try:
        modules_data = json.loads(args.in_modules.read_text(encoding="utf-8"))
        if not isinstance(modules_data, dict):
            modules_data = {"modules": modules_data}
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"planning-validate: cannot read modules.json: {exc}\n")
        return 2

    files_list = None
    if args.in_files_list and args.in_files_list.exists():
        files_list = [ln.strip() for ln in
                      args.in_files_list.read_text(encoding="utf-8").splitlines()
                      if ln.strip()]

    report = validate(modules_data, files_list)
    out_text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_text + "\n", encoding="utf-8")
    print(out_text)

    if args.strict and report["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
