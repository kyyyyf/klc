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

Cross-artifact checks (KLC-071, guarded on the OPTIONAL presence of the views —
absent input degrades to "not checked", never a hard fail):
  - membership <=> eligibility: a shared file (primary_module=null / is_shared in the
    resolver) must be eligible_as_primary:false in file_roles.json, and the reverse
    (planning_indexer.md §"Validation");
  - generated/vendor files and test files are never eligible_as_primary;
  - a high evidence_count module edge must carry file-level evidence;
  - retrieval_trace refs point only at real modules (modules.json) and real files —
    the file universe is file_roles.json ∪ inventory.json (a symbol-bearing file
    absent from file_roles is still real and must not be flagged).

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


def validate(modules_data: dict, files_list: list[str] | None = None,
             file_roles: dict | None = None, module_edges: dict | None = None,
             retrieval: dict | None = None, inventory: dict | None = None) -> dict:
    """Return {"warnings": [...], "errors": [...], "counts": {...}}.

    ``file_roles`` / ``module_edges`` / ``retrieval`` / ``inventory`` are the KLC-071
    cross-artifact inputs. Each is optional: when absent, its checks are skipped
    (recorded in ``counts`` as ``*_checked: False``) rather than failing — the views
    are built degrade-not-fail, so validation must not assume they exist. Retrieval
    file-refs are checked against the real file universe (``file_roles`` ∪
    ``inventory`` files)."""
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

    # --- KLC-071 cross-artifact checks (all optional / degrade-not-fail) --------
    eligibility_checked = False
    roles_files = (file_roles or {}).get("files") or {}
    if roles_files:
        eligibility_checked = True
        for path, rec in sorted(roles_files.items()):
            if not isinstance(rec, dict):
                continue
            eligible = bool(rec.get("eligible_as_primary"))
            roles_shared = "shared" in (rec.get("roles") or [])
            # membership <=> eligibility, BOTH directions (FIX-2a): the resolver
            # (modules.json) and file_roles.json must agree, or the artifacts have
            # drifted (a stale file_roles silently passes today).
            res = _mm.file_to_module(path, modules_data)
            if res["is_shared"]:
                # resolver says shared → file_roles must be ineligible AND marked shared.
                if eligible:
                    warnings.append(
                        f"file_roles[{path}] is a shared file (primary_module=null) "
                        f"but eligible_as_primary=true — must be false")
                elif not roles_shared:
                    warnings.append(
                        f"file_roles[{path}] resolves as shared (member_of "
                        f"{res['member_of']}) but is not marked shared in file_roles "
                        f"— divergent (stale file_roles?)")
            elif res["primary_module"] is not None:
                # resolver owns the file under a primary module → file_roles must NOT
                # call it shared / ownerless.
                if roles_shared or rec.get("module_name") is None:
                    warnings.append(
                        f"file_roles[{path}] is marked shared/ownerless but modules.json "
                        f"resolves it to primary module '{res['primary_module']}' — "
                        f"divergent (stale file_roles?)")
            # generated/vendor files never primary.
            if rec.get("is_generated") and eligible:
                warnings.append(
                    f"file_roles[{path}] is_generated but eligible_as_primary=true "
                    f"— generated/vendor files must not be primary")
            # test files never primary.
            if rec.get("is_test") and eligible:
                warnings.append(
                    f"file_roles[{path}] is_test but eligible_as_primary=true — "
                    f"a test file must not be eligible as a primary file")
    else:
        errors.append("eligibility cross-check skipped: no file_roles supplied")

    edges_checked = False
    edges = (module_edges or {}).get("edges")
    if isinstance(edges, list):
        edges_checked = True
        for e in edges:
            if not isinstance(e, dict):
                continue
            high = (e.get("evidence_count", 0) or 0) >= 3 or e.get("confidence") == "high"
            ev = e.get("evidence") or []
            has_file_ev = any(
                isinstance(x, dict) and x.get("from") and x.get("to") for x in ev)
            if high and not has_file_ev:
                warnings.append(
                    f"module edge {e.get('from')}→{e.get('to')} has high "
                    f"evidence_count but no file-level evidence")

    retrieval_checked = False
    if isinstance(retrieval, dict):
        retrieval_checked = True
        # module refs are checkable against modules.json regardless of file_roles.
        for pm in retrieval.get("primary_modules") or []:
            mn = pm.get("module_name") if isinstance(pm, dict) else pm
            if mn and mn not in valid_names:
                warnings.append(f"retrieval references unknown module: {mn}")
        # file refs: file_roles.json is the AUTHORITATIVE file universe; inventory only
        # WIDENS it (FIX-2b — a symbol-bearing file absent from file_roles is real).
        # When file_roles is ABSENT the authoritative artifact is missing, so the check
        # DEGRADES (skipped + noted) rather than validating against inventory alone —
        # otherwise a real symbol-less config/doc target is false-flagged and --strict
        # fails on a merely-missing view.
        if roles_files:
            inv_files = {s.get("file") for s in (inventory or {}).get("symbols") or []
                         if isinstance(s, dict) and s.get("file")}
            known_files = set(roles_files) | inv_files
            for key in ("files_to_read_first", "files_likely_to_edit",
                        "tests_to_read_or_run"):
                for f in retrieval.get(key) or []:
                    if f not in known_files:
                        warnings.append(
                            f"retrieval[{key}] references unknown file: {f}")
        else:
            errors.append("retrieval file refs not validated: file_roles.json absent "
                          "(authoritative file universe missing)")

    return {
        "warnings": warnings,
        "errors": errors,
        "counts": {
            "modules": len(modules),
            "files_overrides": len(files_map),
            "shared_files": shared_count,
            "orphans": len(orphans),
            "eligibility_checked": eligibility_checked,
            "edges_checked": edges_checked,
            "retrieval_checked": retrieval_checked,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in-modules", type=Path,
                    default=klc_index_dir() / "modules.json")
    ap.add_argument("--in-files-list", type=Path, default=None,
                    help="optional newline-delimited file list for orphan detection")
    ap.add_argument("--in-file-roles", type=Path,
                    default=klc_index_dir() / "file_roles.json",
                    help="optional file_roles.json for the membership⇔eligibility check")
    ap.add_argument("--in-module-edges", type=Path,
                    default=klc_index_dir() / "module_edges.json",
                    help="optional module_edges.json for the high-evidence check")
    ap.add_argument("--in-retrieval", type=Path, default=None,
                    help="optional retrieval_trace.json for the ref-existence check")
    ap.add_argument("--in-inventory", type=Path,
                    default=klc_index_dir() / "inventory.json",
                    help="optional inventory.json — widens the retrieval file universe")
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

    def _opt(path: Path | None) -> dict | None:
        if path and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    report = validate(
        modules_data, files_list,
        file_roles=_opt(args.in_file_roles),
        module_edges=_opt(args.in_module_edges),
        retrieval=_opt(args.in_retrieval),
        inventory=_opt(args.in_inventory))
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
