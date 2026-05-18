#!/usr/bin/env python3
"""file_scanner.py — profile-driven structural scan of a project.

Usage:   file_scanner.py [ROOT]    (ROOT defaults to CWD)

Output:  JSON on stdout:
  {
    "root":           "<abs path>",
    "profile":        "<active profile name>",
    "total_files":    N,
    "total_lines":    N,
    "languages":      { "<lang>": { "files": N, "lines": N } },
    "directory_tree": [ { "path": "src", "files": N } ],
    "entry_points":   [ "<rel path>", ... ],
    "source_roots":   [ { "path": "...", "module": "..." } ]
  }

Excludes, entry patterns, and module discovery mode come from the
active profile's manifest.yml. See profiles/<name>/manifest.yml.

This is a direct port of file-scanner.sh — same contract, same output
shape. The bash version wrapped find/grep/sed/awk/jq; this version
uses pathlib + re + json (no external tools required, works on
Windows without Git Bash).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent

# Baseline excludes always on; profile extends.
BASELINE_RE = re.compile(
    r"(^|/)(\.git|\.klc|node_modules|\.venv|venv|__pycache__|target|build|"
    r"dist|out|bin|obj|\.gradle|\.idea|\.vs|\.next|\.cache|\.serena-cache)(/|$)"
)

EXT_LANG = {
    "py":    "python",
    "ts":    "typescript",
    "tsx":   "typescript",
    "js":    "javascript",
    "jsx":   "javascript",
    "mjs":   "javascript",
    "cjs":   "javascript",
    "rs":    "rust",
    "c":     "c",
    "h":     "c",
    "cc":    "cpp",
    "cpp":   "cpp",
    "cxx":   "cpp",
    "hpp":   "cpp",
    "hh":    "cpp",
    "hxx":   "cpp",
    "cs":    "csharp",
    "java":  "java",
    "kt":    "kotlin",
    "kts":   "kotlin",
    "rb":    "ruby",
    "php":   "php",
    "swift": "swift",
    "uproject": "unreal",
    "uplugin":  "unreal",
}

ENTRY_CANDIDATES = (
    "package.json", "pyproject.toml", "setup.py", "Cargo.toml",
    "CMakeLists.txt", "meson.build", "Makefile",
    "src/index.ts", "src/index.tsx", "src/index.js",
    "index.ts", "index.js",
    "src/main.py", "main.py", "app.py", "__main__.py",
    "src/main.rs", "src/lib.rs",
)


def _resolve_profile_field(field: str) -> str:
    """Shell out to profile-resolve.py. Returns stdout verbatim."""
    script = FRAMEWORK_ROOT / "core" / "skills" / "profile-resolve.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--field", field],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip()


def _line_count(path: Path) -> int:
    """Count newlines in a file. Falls back to 0 on read errors."""
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _ext_of(rel: str) -> str:
    base = rel.rsplit("/", 1)[-1]
    if "." not in base:
        return ""
    return base.rsplit(".", 1)[1].lower()


def _build_excludes_re(root: Path, profile_excludes: str) -> re.Pattern:
    parts = [BASELINE_RE.pattern]
    # When the klc framework is cloned inside the scanned project
    # (layout A), exclude that subdirectory.
    try:
        rel_fw = FRAMEWORK_ROOT.relative_to(root)
        fw_esc = re.escape(str(rel_fw).replace(os.sep, "/"))
        parts.append(rf"(^|/){fw_esc}(/|$)")
    except ValueError:
        pass
    if profile_excludes:
        parts.append(profile_excludes)
    combined = "|".join(f"({p})" for p in parts)
    return re.compile(combined)


def scan(root: Path) -> dict:
    profile = _resolve_profile_field("name") or "generic"
    profile_excludes = _resolve_profile_field("excludes-regex")
    excludes_re = _build_excludes_re(root, profile_excludes)

    module_discovery_raw = _resolve_profile_field("module_discovery") or "{}"
    try:
        module_discovery = json.loads(module_discovery_raw)
    except json.JSONDecodeError:
        module_discovery = {}
    discovery_mode = module_discovery.get("mode", "") or ""
    entry_patterns = module_discovery.get("entry_patterns") or []

    total_files = 0
    total_lines = 0
    lang_files: dict[str, int] = {}
    lang_lines: dict[str, int] = {}
    dir_files: dict[str, int] = {}
    files_rel: list[str] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = str(path.relative_to(root)).replace(os.sep, "/")
        except ValueError:
            continue
        if excludes_re.search(rel):
            continue
        files_rel.append(rel)
        total_files += 1

        ext = _ext_of(rel)
        lang = EXT_LANG.get(ext, "")
        if lang:
            lines = _line_count(path)
            lang_files[lang] = lang_files.get(lang, 0) + 1
            lang_lines[lang] = lang_lines.get(lang, 0) + lines
            total_lines += lines

        top = rel.split("/", 1)[0] if "/" in rel else "."
        dir_files[top] = dir_files.get(top, 0) + 1

    directory_tree = sorted(
        ({"path": k, "files": v} for k, v in dir_files.items()),
        key=lambda e: (-e["files"], e["path"]),
    )
    languages = {
        k: {"files": lang_files[k], "lines": lang_lines[k]}
        for k in lang_files
    }

    entry_points: list[str] = []
    for cand in ENTRY_CANDIDATES:
        if (root / cand).exists():
            entry_points.append(cand)

    # Profile-declared entry patterns (e.g. *.uproject). Case-sensitive
    # glob walk from root honouring excludes.
    for pat in entry_patterns:
        pat = (pat or "").strip()
        if not pat:
            continue
        for hit in root.rglob(pat):
            if not hit.is_file():
                continue
            try:
                rel = str(hit.relative_to(root)).replace(os.sep, "/")
            except ValueError:
                continue
            if excludes_re.search(rel):
                continue
            if rel not in entry_points:
                entry_points.append(rel)

    # Source roots by discovery mode.
    source_roots: list[dict] = []
    if discovery_mode == "build-cs":
        seen: set[tuple[str, str]] = set()
        for hit in root.rglob("*.Build.cs"):
            if not hit.is_file():
                continue
            try:
                rel = str(hit.relative_to(root)).replace(os.sep, "/")
            except ValueError:
                continue
            if excludes_re.search(rel):
                continue
            parent = rel.rsplit("/", 1)[0] if "/" in rel else "."
            module = hit.name[: -len(".Build.cs")]
            key = (parent, module)
            if key in seen:
                continue
            seen.add(key)
            source_roots.append({"path": parent, "module": module})
    elif discovery_mode in ("conventional-dirs", ""):
        for cand in ("src", "lib", "pkg", "internal", "app", "apps", "services"):
            if (root / cand).is_dir():
                source_roots.append({"path": cand, "module": cand})
    else:
        sys.stderr.write(
            f"file-scanner: unknown module_discovery.mode: {discovery_mode!r}\n"
        )
        sys.exit(1)

    return {
        "root":           str(root),
        "profile":        profile,
        "total_files":    total_files,
        "total_lines":    total_lines,
        "languages":      languages,
        "directory_tree": directory_tree,
        "entry_points":   entry_points,
        "source_roots":   source_roots,
    }


def main(argv: list[str]) -> int:
    root = Path(argv[0] if argv else os.getcwd()).resolve()
    if not root.is_dir():
        sys.stderr.write(f"file-scanner: not a directory: {root}\n")
        return 2
    result = scan(root)
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
