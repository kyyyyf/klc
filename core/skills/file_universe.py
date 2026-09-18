#!/usr/bin/env python3
"""file_universe.py — the ONE file-universe resolver and closure predicate every
klc index builder consumes (KLC-105).

Traced down with 5 Whys (spec.md), the defect this closes is not "exclude the agent
worktrees" — it is that a builder must not be allowed to decide for itself what the
project is. ``file_scanner.resolved_file_universe()`` already computes the
authoritative set (git-tracked intersected with the resolved excludes); this module
is the single import point every OTHER builder uses to get that same list, plus the
one closure predicate (``out_of_universe`` / ``closure_report``) that proves a
derived artifact never escaped it.

No builder may enumerate project files by walking the working tree on its own
(``rglob``, ``os.walk``, a private exclude tuple) — every builder either:

  1. is handed ``structural.json`` (or an already-parsed ``structural`` dict) and
     calls ``resolve()``, which adopts ``files_rel`` verbatim when it describes THIS
     root (D-002); or
  2. calls ``resolve()`` with no ``structural`` input at all, in which case it falls
     through to ``file_scanner.resolved_file_universe`` — the SAME resolver
     ``file_scanner.py`` itself uses — never a second, private walk.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_file_dir))
from core.shared.paths import klc_index_dir  # noqa: E402
import file_scanner as _fs  # noqa: E402


def resolve(root: Path, structural: dict | None = None,
            structural_path: Path | None = None) -> dict:
    """Resolve the ONE file universe for *root*.

    Returns ``{"files": [...sorted rel paths...], "source": str, "notes": [str]}``.

    ``source`` is one of:
      - ``"structural.files_rel"`` — a published ``structural.json`` (or an
        already-parsed dict) describing THIS root was adopted verbatim (C-003).
      - ``"git"`` — recomputed via ``git ls-files`` intersected with the resolved
        excludes (the reproducible path).
      - ``"walk"`` — git was unavailable; a single tree walk with the same excludes
        (the documented, non-reproducible degrade path, AC-9).

    D-002: a ``structural`` dict is adopted ONLY when its declared ``root`` resolves
    to the SAME path as *root* — otherwise a builder run against a temp fixture would
    silently inherit the ambient project's universe (e.g. this checkout's, when a
    test forgets to pass its own ``structural``), and every fixture-based closure
    assertion would be validated against the wrong set.
    """
    notes: list[str] = []
    data = structural
    if data is None:
        p = structural_path or (klc_index_dir() / "structural.json")
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                notes.append("structural.json unreadable; universe recomputed")

    if isinstance(data, dict) and isinstance(data.get("files_rel"), list):
        declared = str(data.get("root") or "")
        if declared and Path(declared).resolve() == Path(root).resolve():
            return {
                "files": sorted(f for f in data["files_rel"] if f),
                "source": "structural.files_rel",
                "notes": notes,
            }
        notes.append(
            "structural.json describes a different root; universe recomputed")

    excludes_re = _fs._build_excludes_re(
        Path(root), _fs._resolve_profile_field("excludes-regex"))
    files, src = _fs.resolved_file_universe(Path(root), excludes_re)
    if not files:
        notes.append("file universe is empty (degraded, C-005)")
    return {"files": files, "source": src, "notes": notes}


def members(root: Path, structural: dict | None = None) -> set[str]:
    """Convenience: the resolved universe as a set."""
    return set(resolve(root, structural=structural)["files"])


def by_suffix(files: Sequence[str], suffixes: Sequence[str]) -> list[str]:
    """Universe members whose path ends with one of *suffixes* (e.g. ``(".py",)``)."""
    suf = tuple(suffixes)
    return [f for f in files if f.endswith(suf)]


def out_of_universe(paths: Iterable[str], universe: Iterable[str]) -> list[str]:
    """The ONE closure predicate: sorted, deduped paths that are NOT members of
    *universe*. Empty input, or a fully-closed set, returns ``[]``."""
    known = set(universe)
    return sorted({p for p in paths if p and p not in known})


def collect_index_paths(
    depgraph: dict | None = None,
    inventory: dict | None = None,
    test_map: dict | None = None,
    file_roles: dict | None = None,
    symbol_usage: dict | None = None,
    modules: dict | None = None,
) -> dict[str, list[str]]:
    """Extract the path references AC-2 names from each index artifact, grouped by
    category. A category is present in the result only when its input is not
    ``None`` — callers can pass only the artifacts they have (degrade-not-fail)."""
    out: dict[str, list[str]] = {}

    if depgraph is not None:
        paths: set[str] = set()
        for g in (depgraph.get("import_graphs") or {}).values():
            if not isinstance(g, dict):
                continue
            for node in g.get("nodes") or []:
                if isinstance(node, dict):
                    # D-003: path-carrying graphs (cpp-unreal, madge) must be
                    # checked on their real file path, not the node id — for
                    # cpp-unreal the id is a *.Build.cs module name, never a
                    # repo-relative path, so a closure check over "id" would
                    # test the wrong field entirely.
                    nid = node.get("path") or node.get("id")
                else:
                    nid = node
                if nid:
                    paths.add(nid)
            for e in g.get("edges") or []:
                if not isinstance(e, dict):
                    continue
                for k in ("from", "to"):
                    if e.get(k):
                        paths.add(e[k])
        out["depgraph"] = sorted(paths)

    if inventory is not None:
        out["inventory"] = sorted(
            {s.get("file") for s in inventory.get("symbols") or []
             if isinstance(s, dict) and s.get("file")})

    if test_map is not None:
        paths = set()
        for prod, entry in (test_map.get("production_to_tests") or {}).items():
            if prod:
                paths.add(prod)
            if not isinstance(entry, dict):
                continue
            for t in entry.get("tests") or []:
                if isinstance(t, dict) and t.get("test_file"):
                    paths.add(t["test_file"])
        for tests in (test_map.get("module_to_tests") or {}).values():
            for t in tests or []:
                paths.add(t)
        out["test_map"] = sorted(paths)

    if file_roles is not None:
        out["file_roles"] = sorted((file_roles.get("files") or {}).keys())

    if symbol_usage is not None:
        paths = set()
        for meta in (symbol_usage.get("symbols") or {}).values():
            if not isinstance(meta, dict):
                continue
            if meta.get("defined_in"):
                paths.add(meta["defined_in"])
            for u in meta.get("used_by") or []:
                if isinstance(u, dict) and u.get("file"):
                    paths.add(u["file"])
            for t in meta.get("tested_by") or []:
                if t:
                    paths.add(t)
        out["symbol_usage"] = sorted(paths)

    if modules is not None:
        paths = set()
        for m in modules.get("modules") or []:
            if not isinstance(m, dict):
                continue
            for f in m.get("files") or []:
                if f:
                    paths.add(f)
        for f in (modules.get("files") or {}):
            paths.add(f)
        out["modules"] = sorted(paths)

    return out


def closure_report(categories: dict[str, list[str]],
                    universe: Iterable[str]) -> dict[str, list[str]]:
    """Apply ``out_of_universe`` to every category. Returns ``{category:
    [violations]}`` — a category with no violations maps to ``[]``, never omitted."""
    known = set(universe)
    return {cat: out_of_universe(paths, known) for cat, paths in categories.items()}
