"""module_edges.py — deterministic module reverse-edge aggregation.

Reads file-to-file edges from depgraph.json and maps them to module-level
depends_on / depended_by via longest-prefix path matching.
Deterministic and authoritative; the LLM decompose agent's hand-written
edges are advisory (this overwrites them).
"""
from __future__ import annotations

import copy
from typing import Any


def _file_to_module(filepath: str, path_to_mod: dict[str, str]) -> str | None:
    """Map a file path to its owning module name via longest prefix match."""
    best_len = -1
    best_mod: str | None = None
    for mpath, mname in path_to_mod.items():
        if filepath == mpath or filepath.startswith(mpath + "/"):
            if len(mpath) > best_len:
                best_len = len(mpath)
                best_mod = mname
    return best_mod


def aggregate_module_edges(modules_data: dict, depgraph: dict) -> dict:
    """Return a new modules_data dict with depends_on/depended_by filled
    deterministically from depgraph file edges.

    Args:
        modules_data: dict with {"modules": [...]} shape (object form).
        depgraph: dict with {"import_graphs": {lang: {"edges": [...]}}} shape.

    Returns:
        A deep copy of modules_data with depends_on/depended_by overwritten.
    """
    result = copy.deepcopy(modules_data)
    modules: list[dict] = result.get("modules", [])

    # Build path→module name map (strip trailing slash for consistency)
    path_to_mod: dict[str, str] = {}
    for m in modules:
        mpath = (m.get("path") or "").rstrip("/")
        if mpath:
            path_to_mod[mpath] = m["name"]

    # Collect all file-edge pairs from every language's import_graphs
    all_edges: list[tuple[str, str]] = []
    for lang_data in (depgraph.get("import_graphs") or {}).values():
        for edge in (lang_data.get("edges") or []):
            src = edge.get("from") or ""
            tgt = edge.get("to") or ""
            if src and tgt:
                all_edges.append((src, tgt))

    # Map file edges to module edges (deduplicated, self-edges dropped)
    depends_on: dict[str, set[str]] = {m["name"]: set() for m in modules}
    depended_by: dict[str, set[str]] = {m["name"]: set() for m in modules}

    for src_file, tgt_file in all_edges:
        src_mod = _file_to_module(src_file, path_to_mod)
        tgt_mod = _file_to_module(tgt_file, path_to_mod)
        if src_mod is None or tgt_mod is None:
            continue
        if src_mod == tgt_mod:
            continue
        depends_on[src_mod].add(tgt_mod)
        depended_by[tgt_mod].add(src_mod)

    # Write back (sorted for determinism)
    for m in modules:
        name = m["name"]
        m["depends_on"] = sorted(depends_on.get(name, set()))
        m["depended_by"] = sorted(depended_by.get(name, set()))

    return result
