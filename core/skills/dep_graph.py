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

BASELINE_EXCL = re.compile(
    r"(^|/)(\.git|\.klc|node_modules|\.venv|venv|__pycache__|target|build|"
    r"dist|out|bin|obj|\.gradle|\.idea|\.vs|\.next|\.cache|\.serena-cache)(/|$)"
)


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


def _combined_excl(profile_excludes: str) -> re.Pattern:
    if profile_excludes:
        return re.compile(f"{BASELINE_EXCL.pattern}|{profile_excludes}")
    return BASELINE_EXCL


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


def _madge_typescript(root: Path) -> dict | None:
    """Replace the typescript import graph with madge's richer output
    when `package.json` + madge are present. Returns None on miss."""
    if not (root / "package.json").exists():
        return None
    if not shutil.which("madge"):
        return None
    target = "src" if (root / "src").is_dir() else "."
    try:
        r = subprocess.run(
            ["madge", "--json", target],
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
    nodes = [{"id": f, "path": f} for f in raw]
    edges = [
        {"from": src, "to": tgt}
        for src, tgts in raw.items()
        for tgt in (tgts or [])
    ]
    return {"tool": "madge", "nodes": nodes, "edges": edges, "raw": raw}


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


# ---- UE build-cs ------------------------------------------------------------

_UE_DEP_NAMES = re.compile(
    r"(Public|Private)(Dependency|IncludePath)ModuleNames\s*\.\s*"
    r"(Add|AddRange)\s*\("
)
_STRING_LITERAL = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"')


def _parse_build_cs_deps(path: Path) -> set[str]:
    """Extract referenced module names from a *.Build.cs file.

    Handles Add / AddRange calls, strips // comments, walks parens to
    find the matching close so multi-line arg lists work.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    text = re.sub(r"//[^\n]*", "", text)
    names: set[str] = set()
    for m in _UE_DEP_NAMES.finditer(text):
        i = m.end()
        depth = 1
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        block = text[m.end():i - 1]
        for s in _STRING_LITERAL.findall(block):
            names.add(s)
    return names


def _ue_import_graph(root: Path, excl: re.Pattern) -> dict | None:
    """Build a module-to-module import graph by parsing every *.Build.cs.

    Only runs when the project looks like an Unreal project (has a
    *.uproject file in root or one level deep).
    """
    uproject: Path | None = None
    for p in sorted(root.glob("*.uproject")):
        uproject = p; break
    if uproject is None:
        for p in sorted(root.glob("*/*.uproject")):
            uproject = p; break
    if uproject is None:
        return None

    uproject_dir = uproject.parent
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()

    def _iter_build_cs() -> list[Path]:
        candidates: set[Path] = set()
        for base in (uproject_dir / "Source",
                     uproject_dir / "Plugins",
                     root / "Plugins"):
            if not base.exists():
                continue
            for p in base.rglob("*.Build.cs"):
                try:
                    rel = str(p.relative_to(root)).replace(os.sep, "/")
                except ValueError:
                    continue
                if excl.search(rel):
                    continue
                candidates.add(p)
        return sorted(candidates)

    for build_cs in _iter_build_cs():
        mod_name = build_cs.stem[: -len(".Build")] \
                   if build_cs.stem.endswith(".Build") else build_cs.stem
        try:
            rel_path = str(build_cs.relative_to(root)).replace(os.sep, "/")
        except ValueError:
            rel_path = str(build_cs)
        if mod_name not in seen:
            seen.add(mod_name)
            nodes.append({"id": mod_name, "path": rel_path})
        for dep in sorted(_parse_build_cs_deps(build_cs)):
            if dep not in seen:
                seen.add(dep)
                nodes.append({"id": dep, "path": ""})
            edges.append({"from": mod_name, "to": dep})

    return {
        "tool":  "grep *.Build.cs",
        "nodes": nodes,
        "edges": edges,
        "raw":   str(uproject),
    }


# ---- main -------------------------------------------------------------------

def build(root: Path) -> dict:
    profile_excl = _resolve("excludes-regex")
    excl = _combined_excl(profile_excl)

    try:
        discovery = json.loads(_resolve("module_discovery") or "{}")
    except json.JSONDecodeError:
        discovery = {}
    discovery_mode = discovery.get("mode", "")

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

    # Import graphs via generic scanner.
    scanner_imports, scanner_errors = _import_graphs_from_scanner(root)
    for lang, data in scanner_imports.items():
        add_import(lang, data)
    errors.extend(scanner_errors)

    # madge overrides typescript scanner output.
    madge = _madge_typescript(root)
    if madge:
        add_import("typescript", madge)

    if collect_packages:
        for builder, lang in (
            (_python_package_graph, "python"),
            (_rust_package_graph,   "rust"),
            (_cpp_package_graph,    "cpp"),
        ):
            data, errs = builder(root)
            errors.extend(errs)
            if data:
                add_package(lang, data)

    # UE build-cs import graph.
    if discovery_mode == "build-cs":
        ue = _ue_import_graph(root, excl)
        if ue is not None:
            add_import("cpp-unreal", ue)

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
