#!/usr/bin/env python3
"""dep_graph.py — per-language dependency graphs.

Port of dep-graph.sh. Two graph families are produced:

  import_graphs   - file-to-file / module-to-module edges within the
                    project (used by decompose / context-loader).
  package_graphs  - manifest-level dependency trees (third-party deps).
                    Opt-in via profile field `collect_package_graphs`.

Output on stdout:

  {
    "root":            "<abs>",
    "languages":       ["python", ...],
    "import_graphs":   { "<lang>": { tool, nodes, edges, raw } },
    "package_graphs":  { "<lang>": { tool, nodes, edges, raw } },
    "errors":          ["human-readable messages"]
  }

The skill never hard-fails a language; it appends to `errors` so the
caller can use whichever graphs succeeded.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
import file_universe  # noqa: E402
import index_coverage  # noqa: E402

def _resolve(field: str) -> str:
    script = FRAMEWORK_ROOT / "core" / "skills" / "profile-resolve.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--field", field],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip()


def _import_graphs_from_scanner(root: Path) -> tuple[dict, list[str]]:
    """Invoke core/skills/import-graph.py and split its output per language.

    Returns (per_lang_mapping, errors).
    """
    errors: list[str] = []
    imports: dict[str, dict] = {}
    structural = root / ".klc" / "index" / "structural.json"
    if not structural.exists():
        errors.append(
            "import-graph: structural.json missing; run file-scanner first "
            "for import edges"
        )
        return imports, errors
    script = FRAMEWORK_ROOT / "core" / "skills" / "import-graph.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, cwd=str(root),
            env={**os.environ, "PROJECT_ROOT": str(root)},
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        errors.append(f"import-graph: scanner failed ({e})")
        return imports, errors
    if r.returncode != 0:
        errors.append(
            "import-graph: scanner failed; import edges for "
            "python/rust/typescript unavailable"
        )
        return imports, errors
    try:
        ig = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        errors.append("import-graph: scanner produced invalid JSON")
        return imports, errors
    for lang in ("python", "rust", "typescript"):
        entry = ig.get(lang)
        if entry:
            imports[lang] = {
                "tool":  "import-graph.py",
                "nodes": entry.get("nodes", []),
                "edges": entry.get("edges", []),
                "raw":   None,
            }
    return imports, errors


def _madge_typescript(root: Path, universe: list[str]) -> dict | None:
    """Replace the typescript import graph with madge's richer output
    when `package.json` + madge are present. Returns None on miss.

    KLC-105: madge is an external binary we cannot constrain to the universe, so its
    output is POST-FILTERED; an edge dies with either endpoint (no dangling
    endpoints left in the graph), and the drop count is recorded in ``errors``."""
    if not (root / "package.json").exists():
        return None
    if not shutil.which("madge"):
        return None
    target = "src" if (root / "src").is_dir() else "."
    # KLC-106 AC-6: improve the INPUT to the coverage check, never stand in
    # for it — the flags widen what madge resolves, the verdict in build()
    # still decides whether the result is trustworthy.
    cmd = ["madge", "--json", "--extensions", "ts,tsx,js,jsx"]
    configured = _resolve("tsconfig")
    ts_config = (root / configured) if configured else (root / "tsconfig.json")
    if ts_config.exists():
        cmd += ["--ts-config", str(ts_config)]
    cmd.append(target)
    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, cwd=str(root), timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        raw = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return None
    member = set(universe)
    nodes = [{"id": f, "path": f} for f in raw if f in member]
    edges = [
        {"from": src, "to": tgt}
        for src, tgts in raw.items() if src in member
        for tgt in (tgts or []) if tgt in member
    ]
    dropped = len(raw) - len(nodes)
    return {
        "tool": "madge", "nodes": nodes, "edges": edges, "raw": raw,
        "errors": [f"madge: {dropped} out-of-universe file(s) dropped"] if dropped else [],
    }


def _python_package_graph(root: Path) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    if not any((root / m).exists() for m in
               ("pyproject.toml", "setup.py", "requirements.txt")):
        return None, errors
    if not shutil.which("pipdeptree"):
        errors.append("python: pipdeptree not installed (skipping package graph)")
        return None, errors
    try:
        r = subprocess.run(
            ["pipdeptree", "--json"],
            capture_output=True, text=True, cwd=str(root), timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        errors.append(f"python: pipdeptree failed ({e})")
        return None, errors
    if r.returncode != 0:
        errors.append("python: pipdeptree failed (is the venv active?)")
        return None, errors
    try:
        raw = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        errors.append("python: pipdeptree output unparseable")
        return None, errors
    nodes: list[dict] = []
    edges: list[dict] = []
    for rec in raw:
        pkg = rec.get("package", {})
        pid = pkg.get("key", "")
        if pid:
            nodes.append({"id": pid, "path": ""})
        for dep in rec.get("dependencies") or []:
            dto = dep.get("key", "")
            if pid and dto:
                edges.append({"from": pid, "to": dto})
    return {"tool": "pipdeptree", "nodes": nodes, "edges": edges, "raw": raw}, errors


def _rust_package_graph(root: Path) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    if not (root / "Cargo.toml").exists():
        return None, errors
    if not shutil.which("cargo"):
        errors.append("rust: cargo not installed")
        return None, errors
    try:
        r = subprocess.run(
            ["cargo", "metadata", "--format-version", "1", "--no-deps"],
            capture_output=True, text=True, cwd=str(root), timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        errors.append(f"rust: cargo metadata failed ({e})")
        return None, errors
    if r.returncode != 0:
        errors.append("rust: cargo metadata failed")
        return None, errors
    try:
        raw = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        errors.append("rust: cargo metadata unparseable")
        return None, errors
    nodes: list[dict] = []
    edges: list[dict] = []
    for pkg in raw.get("packages") or []:
        pid = pkg.get("id", "")
        path = pkg.get("manifest_path", "")
        if pid:
            nodes.append({"id": pid, "path": path})
        for dep in pkg.get("dependencies") or []:
            to = dep.get("name", "")
            if pid and to:
                edges.append({"from": pid, "to": to})
    return {"tool": "cargo metadata", "nodes": nodes, "edges": edges, "raw": raw}, errors


def _cpp_package_graph(root: Path) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    if not (root / "CMakeLists.txt").exists() or not shutil.which("cmake"):
        return None, errors
    with tempfile.TemporaryDirectory(prefix="cmake-graphviz-") as tmpdir:
        dot_file = Path(tmpdir) / "deps.dot"
        try:
            r = subprocess.run(
                ["cmake", "-S", str(root), "-B", tmpdir,
                 f"--graphviz={dot_file}"],
                capture_output=True, text=True, timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"cpp: cmake configure failed ({e})")
            return None, errors
        if r.returncode != 0:
            errors.append("cpp: cmake configure failed (project may need custom options)")
            return None, errors
        if not dot_file.exists():
            errors.append("cpp: cmake produced no graphviz output")
            return None, errors
        text = dot_file.read_text(encoding="utf-8", errors="ignore")
        node_re = re.compile(r'"node\d+"\s*\[\s*label\s*=\s*"([^"]+)"')
        nodes = [{"id": m.group(1), "path": ""} for m in node_re.finditer(text)]
        return {
            "tool":  "cmake --graphviz",
            "nodes": nodes,
            "edges": [],
            "raw":   text,
        }, errors


# ---- coverage verdicts (KLC-106) --------------------------------------------

def _node_count(graph: dict) -> int:
    """Distinct files a candidate graph actually covers."""
    ids = {(n.get("path") or n.get("id") or "") for n in graph.get("nodes") or []}
    return len(ids - {""})


def _keep_richer(a: dict, b: dict) -> tuple[dict, dict]:
    """(kept, discarded) — higher node coverage wins; ties break on edge count
    (AC-5). Order of offer never decides, so an external tool can no longer
    silently replace a richer generic-scanner graph."""
    ka, kb = _node_count(a), _node_count(b)
    if ka != kb:
        return (a, b) if ka > kb else (b, a)
    ea, eb = len(a.get("edges") or []), len(b.get("edges") or [])
    return (a, b) if ea >= eb else (b, a)


# ---- main -------------------------------------------------------------------

def build(root: Path) -> dict:
    # KLC-105: the ONE universe — every file-keyed graph this module assembles
    # enumerates only its members (and drops an edge whose endpoint isn't one).
    universe = file_universe.resolve(
        root, structural_path=root / ".klc" / "index" / "structural.json")["files"]

    collect_packages = (_resolve("collect_package_graphs") or "false").lower() == "true"

    imports: dict[str, dict] = {}
    packages: dict[str, dict] = {}
    errors: list[str] = []
    languages: list[str] = []

    def add_import(lang: str, data: dict) -> None:
        imports[lang] = data
        if lang not in languages:
            languages.append(lang)

    def add_package(lang: str, data: dict) -> None:
        packages[lang] = data
        if lang not in languages:
            languages.append(lang)

    # KLC-106: structural.json read once, behind the tolerant loader — it is
    # the coverage denominator for every file-scoped producer below (AC-3).
    structural = index_coverage.load_json_or_none(
        root / ".klc" / "index" / "structural.json")

    def _stamp_and_record(entry: dict, builder: str, artifact: str, scope) -> dict:
        """Stamp `degraded`/`reason` onto *entry* and append its verdict to
        `errors[]` (AC-4). `scope=None` means "not file-scoped" (D-002): a
        producer whose nodes are not files records `metric: not-applicable`
        rather than a fabricated ratio."""
        if scope is None:
            v = index_coverage.verdict(
                f"dep_graph:{builder}", artifact, _node_count(entry), None,
                metric=index_coverage.NOT_APPLICABLE)
        else:
            v = index_coverage.verdict(
                f"dep_graph:{builder}", artifact, _node_count(entry),
                index_coverage.universe_for(scope, structural),
                metric="node-coverage")
        entry["degraded"], entry["reason"] = v["degraded"], v["reason"]
        errors.append(v)
        return entry

    # Each producer OFFERS a candidate for a language; coverage decides which
    # one is kept, not call order (AC-5). `scope` is the universe_for() key,
    # or None for a producer whose nodes are not files (D-002).
    import_candidates: dict[str, list[tuple[dict, str | None]]] = {}

    def offer_import(lang: str, data: dict, scope) -> None:
        import_candidates.setdefault(lang, []).append((data, scope))

    # Import graphs via generic scanner.
    scanner_imports, scanner_errors = _import_graphs_from_scanner(root)
    for lang, data in scanner_imports.items():
        offer_import(lang, data, lang)
    errors.extend(scanner_errors)

    # madge OFFERS a typescript candidate; it no longer overwrites the
    # scanner's unconditionally (AC-5 — the ticket's originating bug).
    madge = _madge_typescript(root, universe)
    if madge:
        offer_import("typescript", madge, "typescript")

    if collect_packages:
        for builder, lang in (
            (_python_package_graph, "python"),
            (_rust_package_graph,   "rust"),
            (_cpp_package_graph,    "cpp"),
        ):
            data, errs = builder(root)
            errors.extend(errs)
            if data:
                # Package graphs have no natural file denominator (Q-005,
                # D-002): manifest-level nodes are packages, not files.
                add_package(lang, _stamp_and_record(
                    data, data.get("tool", builder.__name__), "depgraph.json", None))

    for lang, offers in import_candidates.items():
        scope = offers[0][1]
        kept = offers[0][0]
        for other, _scope in offers[1:]:
            kept, poorer = _keep_richer(kept, other)
            # Record the discarded candidate's own verdict too (AC-5): its
            # tool name and ratio land in errors[] even though it lost.
            _stamp_and_record(dict(poorer), poorer.get("tool", "?"),
                               "depgraph.json", scope)
        errors.extend(kept.get("errors") or [])
        add_import(lang, _stamp_and_record(
            kept, kept.get("tool", "?"), "depgraph.json", scope))

    return {
        "root":           str(root),
        "languages":      languages,
        "import_graphs":  imports,
        "package_graphs": packages,
        "errors":         errors,
    }


def main(argv: list[str]) -> int:
    root = Path(argv[0] if argv else os.getcwd()).resolve()
    if not root.is_dir():
        sys.stderr.write(f"dep-graph: not a directory: {root}\n")
        return 2
    result = build(root)
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
