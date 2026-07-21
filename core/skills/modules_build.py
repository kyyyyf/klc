#!/usr/bin/env python3
"""modules_build.py — deterministic modules.json v2 clustering (KLC-066).

Replaces the LLM `decompose` agent's *membership* decision with a deterministic,
byte-reproducible clustering derived from the structural scan and (optionally) the
import graph. KLC-074 CUT OVER to this build: `decompose.md` is fully RETIRED from
the pipeline (init.py no longer runs it) — it is not demoted to an annotator, it is
gone. Module `name` is the path-derived slug; membership, edges, roles, and the
`files` override map are all deterministic. Any `summary`/`keywords` enrichment is a
possible future follow-up over the deterministic set, NOT part of this pipeline
(planning_indexer.md §"Детерминированные данные — source of truth").

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
  - Candidate files = the union of (a) the import-graph node ids + edge endpoints
    across languages and (b) the full tracked-file listing (`all_files`, KLC-074).
    (a) alone only saw CODE files (Python/TS import nodes), so every non-code
    directory — `docs/`, `core/agents/` (agent markdown), `config/` (yaml),
    `core/templates/`, `klc-plugin/*` — produced NO module and its files ORPHANED
    (the KLC-074 cut-over measured this over the real archive: 383 orphan touched-
    file instances across 54 archived tickets). Feeding the full file listing makes
    every directory that holds a tracked file a module, so those files resolve
    instead of orphaning. When no `all_files` is given the old depgraph-only /
    directory_tree behaviour is preserved (back-compat for the pure unit tests).
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
sys.path.insert(0, str(_file_dir))
from core.shared.paths import klc_index_dir, project_root  # noqa: E402
# KLC-074 review HIGH-1/HIGH-2: the module file universe is file_scanner's resolved
# universe (git-tracked ∩ profile/framework/baseline excludes), NOT a raw os.walk, so
# the module SET is byte-reproducible across machines and consistent with the scan.
import file_scanner as _fs  # noqa: E402


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


def module_file_universe(root: Path,
                         structural: dict | None = None) -> tuple[list[str] | None, str]:
    """The authoritative file universe fed to ``build_modules`` (KLC-074 review).

    Sorted, git-tracked, and consistent with the structural scan BY CONSTRUCTION:

      1. Primary — ``structural["files_rel"]`` when present. file_scanner already
         resolved it (git-tracked ∩ profile/framework/baseline excludes), so consuming
         it means the module SET cannot diverge from the scan universe.
      2. Fallback — ``file_scanner.resolved_file_universe`` (``git ls-files`` filtered
         by the SAME resolved excludes) when structural has no ``files_rel``.

    NEVER a raw working-tree ``os.walk``: untracked/gitignored junk must not fabricate
    modules (that would make two checkouts at the same HEAD compute different sets).

    Returns ``(files, source)``. **``files`` distinguishes two very different cases
    (KLC-074 review P2):**
      - ``[]``   — the universe is legitimately EMPTY (e.g. a git repo whose only files
                   are untracked/excluded). The caller must build ZERO modules, NOT
                   fall back — falling back would re-fabricate modules from the very
                   untracked/excluded files the universe dropped (reopening HIGH-1).
      - ``None`` — the authoritative git-tracked universe could NOT be determined (no
                   ``files_rel`` AND git unavailable, so only a non-reproducible walk is
                   possible). The caller degrades to depgraph-only clustering."""
    if structural and isinstance(structural.get("files_rel"), list):
        # file_scanner resolved this (git-tracked ∩ excludes); [] here is legit-empty.
        return sorted(f for f in structural["files_rel"] if f), "structural.files_rel"
    profile_excludes = _fs._resolve_profile_field("excludes-regex")
    excludes_re = _fs._build_excludes_re(root, profile_excludes)
    files, src = _fs.resolved_file_universe(root, excludes_re)
    if src != "git":
        # git unavailable / not a checkout → only a raw walk was possible, which is not
        # an authoritative git-tracked universe. Signal 'cannot determine' with None.
        return None, f"resolved_file_universe:{src}(non-authoritative)"
    return files, f"resolved_file_universe:{src}"


def build_modules(structural: dict, depgraph: dict | None = None,
                  all_files: list[str] | None = None) -> dict:
    """Deterministically cluster files into modules. Pure: no timestamp, no I/O.

    ``all_files`` (KLC-074) is the full tracked-file listing gathered by ``main()``
    (byte-sorted). When supplied it is unioned with the import-graph nodes so every
    directory holding a tracked file becomes a module — non-code directories no
    longer orphan. Passing the SAME ``all_files`` list makes the result byte-
    identical on re-run (the pure-function contract, AC-3). When it is ``None`` the
    old depgraph-only / directory_tree fallback is used unchanged.

    Returns the modules.json v2 object (membership fields only). See module
    docstring for the algorithm and the empty-`files`-map rationale.
    """
    errors: list[str] = []
    notes: list[str] = []

    graph_files = _candidate_files(depgraph)
    # KLC-074 review P2: `is not None` — an EMPTY authoritative universe ([]) means
    # "zero modules", NOT "no universe → fall back". Only None (universe genuinely
    # unavailable) falls through to the depgraph/directory_tree clustering below.
    if all_files is not None:
        # KLC-074 cut-over: cluster the FULL tracked-file listing so non-code dirs
        # are covered. The listing is the AUTHORITATIVE git-tracked ∩ excludes
        # universe, so it already contains every tracked, non-excluded code file.
        # Depgraph import-graph nodes are therefore used only to INTERSECT — an
        # untracked or scanner-excluded file that leaked into the import graph (e.g.
        # a committed `build/` artifact, or an untracked `.py`) must NOT re-introduce
        # a module the universe deliberately dropped (KLC-074 review HIGH-1/HIGH-2).
        files = sorted(set(all_files))
        source = "file_listing"
    elif graph_files:
        files = graph_files
        source = "depgraph"
    else:
        # Degrade: no import graph AND no file listing → fall back to the coarse
        # top-level directory tree. This is honest but coarser; note it so the
        # operator knows why the module set is shallow.
        files = []
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

    if source in ("depgraph", "file_listing"):
        notes.append(
            "membership is directory-level (KLC-074 cut-over: intentional — file-stem "
            "modules need a non-reproducible semantic judgement); finer per-file "
            "targeting is delivered by the KLC-070/071 file-level views (file_roles, "
            "inventory, symbol_usage), a separate layer from the module SET."
        )
        # KLC-074 review MEDIUM-1: this deterministic build emits NO shared entries
        # (`files[path].member_of` with primary_module=null), so file_to_module never
        # returns is_shared=True and the shared-file branch in scope_delta.py (utility
        # edits → drift/warning instead of expansion) is currently INERT. It re-arms
        # only once the KLC-070 inventory feeds a real member_of map here. Consequently
        # the scope-expansion guard is COARSER under directory-level modules (a ticket
        # scoped to `core/skills` covers any edit under it). This is an accepted
        # trade-off of the cut-over; a compensating file-level check is a follow-up,
        # NOT silently dropped. See the KLC-074 design/retrospective.
        notes.append(
            "shared-file classification (member_of) is not emitted yet — the "
            "scope_delta shared branch is inert until the KLC-070 inventory feeds it; "
            "scope expansion is coarser at directory granularity (KLC-074 review)."
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
    ap.add_argument("--root", type=Path, default=None,
                    help="repo root for the file-universe resolution (KLC-074). "
                         "Defaults to PROJECT_ROOT. Pass --no-walk to skip the "
                         "full-file universe and fall back to depgraph-only clustering.")
    ap.add_argument("--no-walk", action="store_true",
                    help="skip the full-file universe (depgraph-only clustering).")
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

    # KLC-074: resolve the git-tracked, scanner-consistent file universe so non-code
    # directories become modules instead of orphaning — without letting untracked junk
    # fabricate modules. Degrade-not-fail: if resolution raises, fall back to
    # depgraph-only clustering with a note rather than aborting.
    all_files: list[str] | None = None
    if not args.no_walk:
        root = args.root or project_root()
        try:
            all_files, universe_src = module_file_universe(root, structural)
        except OSError as exc:
            sys.stderr.write(
                f"modules_build: file-universe resolution of {root} failed ({exc}); "
                f"degrading to depgraph-only clustering\n")
            all_files, universe_src = None, "error"
        if all_files is None:
            # None = universe genuinely unavailable (see module_file_universe): degrade
            # to depgraph-only. An EMPTY universe ([]) is NOT None — it flows through as
            # zero modules (KLC-074 review P2).
            sys.stderr.write(
                f"modules_build: authoritative file universe unavailable "
                f"({universe_src}); degrading to depgraph-only clustering\n")
        else:
            sys.stderr.write(
                f"modules_build: file universe ({len(all_files)} files) "
                f"from {universe_src}\n")

    result = build_modules(structural, depgraph, all_files)
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
