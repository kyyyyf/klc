#!/usr/bin/env python3
"""import-graph.py — per-language file-level import graph (project-internal).

Reads `.klc/index/structural.json` for `source_roots` and scans the
matching files for imports. Resolves each import to an internal file path
using a small language-specific resolver. Imports to third-party packages
(those not reachable via `source_roots`) are dropped — they belong in the
package graph, not here.

Output on stdout, JSON:

    {
      "python":     { "tool": "import-graph.py", "nodes": [...], "edges": [...] },
      "rust":       { "tool": "import-graph.py", "nodes": [...], "edges": [...] },
      "typescript": { "tool": "import-graph.py", "nodes": [...], "edges": [...] }
    }

Each edge is { "from": "<source_rel_path>", "to": "<target_rel_path>" }.
Only languages with at least one source file in `source_roots` appear.

This is a best-effort static scan; it does not understand dynamic imports,
__import__, re-exports through barrels with renaming, or Rust macros that
generate `use`. For languages that need precision, prefer an LSP-backed
signal.
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
sys.path.insert(0, str(_file_dir))
from core.shared.paths import framework_root, klc_index_dir  # noqa: E402, F401
import file_universe  # noqa: E402


# ---- tiny regex-based parsers ----------------------------------------------

# Python: `import a`, `from a import b`, `from .a import b` (relative).
RE_PY_IMPORT = re.compile(r"^\s*(?:from\s+(?P<from>\.?[\w\.]+)\s+import\b|import\s+(?P<module>[\w\.]+))")

# Rust: `use a::b::c;`, `mod foo;`.
RE_RS_USE = re.compile(r"^\s*(?:pub\s+)?use\s+(?P<path>[\w:]+)\b")
RE_RS_MOD = re.compile(r"^\s*(?:pub\s+)?mod\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;")

# TypeScript/JavaScript: `import ... from "./a"`, `import "./a"`, CJS require.
RE_TS_FROM = re.compile(r"""^\s*(?:import|export)\b[^'"]*?from\s+['"](?P<path>[^'"]+)['"]""")
RE_TS_BARE = re.compile(r"""^\s*import\s+['"](?P<path>[^'"]+)['"]""")
RE_TS_REQ  = re.compile(r"""require\(\s*['"](?P<path>[^'"]+)['"]\s*\)""")


def load_structural() -> dict:
    p = klc_index_dir() / "structural.json"
    if not p.exists():
        sys.stderr.write(f"import-graph: {p} missing; run file-scanner first\n")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


# ---- per-language scanners --------------------------------------------------

def _collect_files(root: Path, source_roots: list[str], extensions: tuple[str, ...],
                   universe: list[str]) -> list[Path]:
    """Collect universe members with any of the extensions under source_roots. If no
    source_root contains a matching file, fall back to every universe member with a
    matching extension (this handles projects whose source_roots describe a
    different language, e.g. UE where source_roots are Build.cs dirs but python
    support tooling lives elsewhere) — the SAME fallback semantics as before
    (KLC-105), but drawn from the resolved universe instead of an independent
    ``rglob`` walk plus a hard-coded exclusion tuple."""
    hits = [f for f in universe if f.endswith(extensions)]
    under = [f for f in hits
             if any(f == sr or f.startswith(sr + "/") for sr in source_roots)]
    return [root / f for f in (under or hits)]


def scan_python(root: Path, source_roots: list[str],
                universe: list[str]) -> tuple[list, list]:
    files = _collect_files(root, source_roots, (".py",), universe)

    # Build a module-name -> file index so we can resolve `import foo.bar.baz`
    # to an internal file. Key is the dotted module path relative to the
    # closest `__init__.py`-rooted package root; fall back to the filename.
    mod_index: dict[str, Path] = {}
    for f in files:
        rel = f.relative_to(root)
        dotted = ".".join(rel.with_suffix("").parts)
        mod_index[dotted] = f
        # Also index by last segment (helps `from X import Y` where X is
        # top-level) — but only when unique, otherwise ambiguous.
        last = rel.with_suffix("").name
        if last != "__init__":
            mod_index.setdefault(last, f)

    nodes = [{"id": str(f.relative_to(root)).replace("\\", "/")} for f in files]
    edges = []
    for f in files:
        src_rel = str(f.relative_to(root)).replace("\\", "/")
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            m = RE_PY_IMPORT.match(line)
            if not m:
                continue
            mod = (m.group("from") or m.group("module") or "").strip(".")
            if not mod:
                continue
            # Try dotted match first, then last-segment.
            target = mod_index.get(mod) or mod_index.get(mod.split(".")[0])
            if target and target != f:
                edges.append({
                    "from": src_rel,
                    "to":   str(target.relative_to(root)).replace("\\", "/"),
                })
    return nodes, edges


def scan_rust(root: Path, source_roots: list[str],
             universe: list[str]) -> tuple[list, list]:
    files = _collect_files(root, source_roots, (".rs",), universe)

    nodes = [{"id": str(f.relative_to(root)).replace("\\", "/")} for f in files]

    # Build a crate-local path index. `mod foo;` resolves to `foo.rs` or
    # `foo/mod.rs` next to the referencing file — we approximate by filename.
    by_name: dict[str, list[Path]] = {}
    for f in files:
        by_name.setdefault(f.stem, []).append(f)

    edges = []
    for f in files:
        src_rel = str(f.relative_to(root)).replace("\\", "/")
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            m = RE_RS_MOD.match(line) or RE_RS_USE.match(line)
            if not m:
                continue
            if m.re is RE_RS_MOD:
                target_name = m.group("name")
            else:
                # `use a::b::c;` — first segment is a crate/module root.
                target_name = m.group("path").split("::")[0]
            candidates = by_name.get(target_name, [])
            for tgt in candidates:
                if tgt == f:
                    continue
                edges.append({
                    "from": src_rel,
                    "to":   str(tgt.relative_to(root)).replace("\\", "/"),
                })
    return nodes, edges


def scan_ts(root: Path, source_roots: list[str],
           universe: list[str]) -> tuple[list, list]:
    files = _collect_files(root, source_roots,
                           (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"),
                           universe)
    member = set(universe)

    files_rel = {str(f.relative_to(root)).replace("\\", "/"): f for f in files}
    nodes = [{"id": k} for k in files_rel]

    def resolve_relative(from_file: Path, spec: str) -> Path | None:
        if not spec.startswith("."):
            return None  # bare import — package graph's job
        target = (from_file.parent / spec).resolve()
        # Try as-is and with common extensions.
        for cand in (target,
                     target.with_suffix(".ts"),
                     target.with_suffix(".tsx"),
                     target.with_suffix(".js"),
                     target.with_suffix(".jsx"),
                     target / "index.ts",
                     target / "index.tsx",
                     target / "index.js"):
            if cand.exists() and cand.is_file():
                return cand
        return None

    edges = []
    for f in files:
        src_rel = str(f.relative_to(root)).replace("\\", "/")
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            m = RE_TS_FROM.match(line) or RE_TS_BARE.match(line)
            spec = m.group("path") if m else None
            if not spec:
                m2 = RE_TS_REQ.search(line)
                spec = m2.group("path") if m2 else None
            if not spec:
                continue
            tgt = resolve_relative(f, spec)
            if tgt is None:
                continue
            try:
                tgt_rel = str(tgt.resolve().relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            # KLC-105: a resolved relative import may land on an untracked file —
            # drop it, otherwise the edge ENDPOINT escapes the universe (AC-2 counts
            # endpoints, not just node ids).
            if tgt_rel not in member:
                continue
            edges.append({"from": src_rel, "to": tgt_rel})
    return nodes, edges


# ---- driver -----------------------------------------------------------------

LANG_SCANNERS = {
    "python":     ("py", scan_python),
    "rust":       ("rs", scan_rust),
    "typescript": ("ts", scan_ts),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--structural", type=Path,
                    help="override path to structural.json")
    args = ap.parse_args()

    structural = json.loads((args.structural or (klc_index_dir() / "structural.json")).read_text(encoding="utf-8"))
    root = Path(structural["root"]).resolve()
    source_roots = [r["path"] for r in structural.get("source_roots", [])]
    languages = structural.get("languages", {})
    # KLC-105: the ONE universe (adopts structural["files_rel"] since root matches,
    # D-002) — every scanner enumerates only its members, never an independent walk.
    universe = file_universe.resolve(root, structural=structural)["files"]

    out: dict = {}
    for lang, (_ext, scanner) in LANG_SCANNERS.items():
        if lang not in languages:
            continue
        nodes, edges = scanner(root, source_roots, universe)
        if not nodes and not edges:
            continue
        out[lang] = {"tool": "import-graph.py", "nodes": nodes, "edges": edges}

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
