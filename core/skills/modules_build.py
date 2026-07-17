#!/usr/bin/env python3
"""modules_build.py — deterministic modules.json v2 clustering (KLC-066).

Replaces the LLM `decompose` agent's *membership* decision with a deterministic,
byte-reproducible clustering derived from the structural scan and (optionally) the
import graph. The LLM (`decompose.md`, now demoted) only annotates the result with
`name`(label)/`summary`/`keywords`; it never decides membership, edges, roles, or
the `files` override map (planning_indexer.md §"Детерминированные данные —
source of truth").

What it produces (the deterministic MODULE-LEVEL fields):
    {
      "modules": [
        {"name": "<slug>", "path": "<dir>/", "files": [...sorted...],
         "primary_entrypoints": [...], "source": "depgraph|directory_tree",
         "depends_on": [], "depended_by": []}
      ],
      "files": {...},       # per-file override map. Contains only repo-ROOT file
                            # overrides here (FIX-2 — root files have no
                            # longest-prefix path). The broader out-of-path /
                            # shared-multi-module classification needs a per-file
                            # inventory listing (the deterministic inventory skill,
                            # KLC-070). module_membership.file_to_module() already
                            # supports the full map and the KLC-066 fuzz gate
                            # proves it; non-root files resolve by longest-prefix.
      "errors": [...],      # degrade-not-fail notes (e.g. depgraph missing)
      "notes":  [...]
    }

`build_modules(structural, depgraph)` is a PURE function with no timestamp, so it
is byte-identical on re-run (AC-3). `path` stays the canonical longest-prefix key
and `name` a stable slug (AC-4); no `id`, no `root_paths`.

Clustering rule (deterministic):
  - Candidate files = the union of import-graph node ids + edge endpoints across
    languages (a real per-file listing) when a depgraph is given; otherwise the
    top-level directories from structural.directory_tree (coarser, with a note).
  - Each file is clustered by its immediate parent directory. One module per
    directory that directly contains at least one candidate file.
  - Module path = "<dir>/" (trailing slash → the resolver's raw-startswith needs
    the boundary, avoiding `foo/` matching `foobar/`). Module name = the path with
    the trailing slash stripped (matches the existing dir-module naming, e.g.
    "core/skills"). Everything is sorted for byte-stability.

CLI convention (like dep_graph.py / file_scanner.py):
    modules_build.py --in-structural <p> --in-depgraph <p> --out-modules <p>
  defaults to klc_index_dir() paths; PROJECT_ROOT from env; exit 0 ok / exit 2 on
  a missing required input (structural) or a bad path; a missing OPTIONAL depgraph
  degrades into errors[] rather than failing.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
from core.shared.paths import klc_index_dir  # noqa: E402


def _slug_from_path(dir_path: str) -> str:
    """Canonical module name for a directory path. Stable and reversible enough:
    the trailing slash is stripped; the rest is the path itself (KLC module names
    are path-derived slugs, e.g. 'core/skills')."""
    return dir_path.rstrip("/")


def _candidate_files(depgraph: dict | None) -> list[str]:
    """Every file path mentioned by the import graphs (nodes + edge endpoints)."""
    files: set[str] = set()
    for lang_graph in ((depgraph or {}).get("import_graphs") or {}).values():
        for node in lang_graph.get("nodes") or []:
            nid = node.get("id") if isinstance(node, dict) else node
            if nid:
                files.add(nid)
        for edge in lang_graph.get("edges") or []:
            for key in ("from", "to"):
                v = edge.get(key)
                if v:
                    files.add(v)
    return sorted(files)


def build_modules(structural: dict, depgraph: dict | None = None) -> dict:
    """Deterministically cluster files into modules. Pure: no timestamp, no I/O.

    Returns the modules.json v2 object (membership fields only). See module
    docstring for the algorithm and the empty-`files`-map rationale.
    """
    errors: list[str] = []
    notes: list[str] = []

    files = _candidate_files(depgraph)
    source = "depgraph"
    if not files:
        # Degrade: no import graph → fall back to the coarse top-level directory
        # tree. This is honest but coarser; note it so the operator knows why the
        # module set is shallow.
        errors.append("depgraph absent/empty — clustering from structural."
                      "directory_tree (coarse, top-level directories only)")
        source = "directory_tree"
        for entry in structural.get("directory_tree") or []:
            p = (entry.get("path") or "").strip()
            if p and p not in (".",) and not p.startswith("."):
                files.append(p.rstrip("/") + "/__dir__")  # sentinel per directory
        files = sorted(set(files))

    # Cluster each file by its immediate parent directory. Repo-root files
    # (dirname == "") are handled separately: they cannot be expressed as a
    # longest-prefix path (an empty/"./" path matches nothing), so they are
    # registered as explicit `files` overrides instead (FIX-2).
    by_dir: dict[str, list[str]] = {}
    root_files: list[str] = []
    for f in files:
        parent = os.path.dirname(f)
        if not parent:
            root_files.append(f)
        else:
            by_dir.setdefault(parent + "/", []).append(f)

    entry_points = sorted(structural.get("entry_points") or [])

    modules: list[dict] = []
    for dir_path in sorted(by_dir):
        member_files = sorted(fp for fp in by_dir[dir_path]
                              if not fp.endswith("/__dir__"))
        primary_entrypoints = sorted(
            ep for ep in entry_points if ep.startswith(dir_path)
        )
        modules.append({
            "name": _slug_from_path(dir_path),
            "path": dir_path,
            "files": member_files,
            "primary_entrypoints": primary_entrypoints,
            "source": source,
            "depends_on": [],       # filled deterministically by module_edges.py
            "depended_by": [],      # filled deterministically by module_edges.py
        })

    # Root-level module. Repo-root files (dirname == "") have no longest-prefix
    # path, so each is pinned via a `files` override so file_to_module() attributes
    # it instead of orphaning it (FIX-2 round 1). The module's own path is the
    # sentinel "." (NOT "") — a falsy path makes public-api-filter treat the module
    # as having no authored symbols and drop its public API (FIX-2 round 2). "."
    # is truthy so public-api-filter honours it, yet the resolver never matches it
    # via longest-prefix (root files resolve only through the override), so it
    # cannot over-match any other file.
    files_map: dict[str, dict] = {}
    root_files = sorted(fp for fp in set(root_files) if not fp.endswith("/__dir__"))
    if root_files:
        root_name = "."
        modules.append({
            "name": root_name,
            "path": ".",
            "files": root_files,
            "primary_entrypoints": sorted(ep for ep in entry_points if "/" not in ep),
            "source": source,
            "depends_on": [],
            "depended_by": [],
        })
        for rf in root_files:
            files_map[rf] = {"primary_module": root_name}

    if source == "depgraph":
        notes.append(
            "membership is directory-level; finer file-module granularity and the "
            "per-file `files` override/shared map require the deterministic "
            "inventory skill (KLC-070)."
        )

    return {
        "modules": modules,
        # Contains only repo-root file overrides (FIX-2). The broader per-file
        # override / shared-classification map still needs the KLC-070 inventory;
        # the resolver already supports both and the fuzz gate proves it.
        "files": files_map,
        "errors": errors,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic modules.json v2 clustering")
    ap.add_argument("--in-structural", type=Path,
                    default=klc_index_dir() / "structural.json")
    ap.add_argument("--in-depgraph", type=Path,
                    default=klc_index_dir() / "depgraph.json")
    ap.add_argument("--out-modules", type=Path,
                    default=klc_index_dir() / "modules.json")
    args = ap.parse_args(argv)

    if not args.in_structural.exists():
        sys.stderr.write(
            f"modules_build: required input {args.in_structural} not found\n")
        return 2
    try:
        structural = json.loads(args.in_structural.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"modules_build: cannot read structural.json: {exc}\n")
        return 2

    depgraph = None
    if args.in_depgraph.exists():
        try:
            depgraph = json.loads(args.in_depgraph.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # optional input → degrade, don't fail
            depgraph = None
            sys.stderr.write(
                f"modules_build: depgraph unreadable ({exc}); degrading\n")

    result = build_modules(structural, depgraph)
    # generated_at/git_sha live only at the top level of the written file so the
    # membership fields stay byte-identical across runs.
    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    args.out_modules.parent.mkdir(parents=True, exist_ok=True)
    args.out_modules.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for e in result["errors"]:
        sys.stderr.write(f"modules_build: warning: {e}\n")
    print(f"modules_build: wrote {len(result['modules'])} module(s) to "
          f"{args.out_modules}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
