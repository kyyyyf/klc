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

KLC-105: `total_files`, `total_lines`, `languages`, `directory_tree`, `entry_points`
and `source_roots` are all derived from the SAME resolved file universe
(`files_rel`) that `resolved_file_universe()` already computed for the reproducible
`files_rel` field — not from an independent `rglob` walk. Before this change the two
counted 4978 (walk) vs 486 (universe) on this checkout, because `.claude/worktrees`
agent copies matched no exclude pattern. `total_files`/`languages`/`directory_tree`
therefore change meaning from "files on disk after excludes" to "files in the
universe" (spec.md `counter-semantics`); they are diagnostics inside the index, not
a published API.
"""
from __future__ import annotations

import fnmatch
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


def _to_posix(rel: str) -> str:
    """Normalise an OS-native relative-path string to POSIX '/'-separators.

    Extracted so the normalisation itself is unit-testable independent of the
    runner's actual ``os.sep`` (a test built with native ``Path`` objects on a
    POSIX runner never produces a backslash to normalise, and asserting on it
    would be vacuously true there — see test_klc105_edge_cases.py review)."""
    return rel.replace(os.sep, "/")


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
        fw_esc = re.escape(_to_posix(str(rel_fw)))
        parts.append(rf"(^|/){fw_esc}(/|$)")
    except ValueError:
        pass
    if profile_excludes:
        parts.append(profile_excludes)
    combined = "|".join(f"({p})" for p in parts)
    return re.compile(combined)


def _git_tracked_files(root: Path) -> list[str] | None:
    """Repo-relative POSIX paths of every GIT-TRACKED file (`git ls-files`, which
    already honours `.gitignore`). Returns None when *root* is not a git checkout or
    git is unavailable, so callers can degrade. This is what makes the file universe
    reproducible across machines: two checkouts at the same HEAD list the same set,
    regardless of untracked working-tree junk."""
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.split("\0") if p]


def resolved_file_universe(root: Path, excludes_re: re.Pattern) -> tuple[list[str], str]:
    """The authoritative scan/module file universe: GIT-TRACKED ∩ NOT-excluded, sorted.

    (KLC-074 review HIGH-1/HIGH-2.) The universe is the git-tracked set (reproducible
    across machines, no untracked junk) filtered by the SAME resolved excludes the
    scan uses (baseline + profile ``excludes-regex`` + layout-A framework-root), so a
    tracked-but-excluded path (e.g. a committed ``build/`` artifact, or the nested klc
    framework) is dropped too.

    Returns ``(files, source)`` where source is ``"git"`` (authoritative) or
    ``"walk"`` (degrade: git unavailable → rglob the tree with the SAME excludes; a
    best-effort fallback so a non-git project still scans, but NOT reproducible)."""
    tracked = _git_tracked_files(root)
    if tracked is not None:
        return sorted(f for f in tracked if f and not excludes_re.search(f)), "git"
    walked: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = _to_posix(str(path.relative_to(root)))
        except ValueError:
            continue
        if excludes_re.search(rel):
            continue
        walked.append(rel)
    return sorted(walked), "walk"


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

    # KLC-105: the ONE file universe (git-tracked ∩ resolved excludes, or the walk
    # degrade path) drives every counter below — no independent rglob walk. Moved
    # above the counter loop (was computed ten lines further down, after an
    # independent walk had already produced total_files/languages/directory_tree
    # from a DIFFERENT set — 4978 vs 486 on this checkout before the fix).
    files_rel, files_rel_source = resolved_file_universe(root, excludes_re)

    total_files = 0
    total_lines = 0
    lang_files: dict[str, int] = {}
    lang_lines: dict[str, int] = {}
    dir_files: dict[str, int] = {}

    for rel in files_rel:
        total_files += 1

        ext = _ext_of(rel)
        lang = EXT_LANG.get(ext, "")
        if lang:
            lines = _line_count(root / rel)
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

    # Profile-declared entry patterns (e.g. *.uproject). KLC-105: matched against the
    # resolved universe (files_rel), not an independent glob walk — a pattern with no
    # "/" matches by basename (rglob(pat) semantics), a pattern with "/" matches the
    # full relative path.
    for pat in entry_patterns:
        pat = (pat or "").strip()
        if not pat:
            continue
        for rel in files_rel:
            base = rel.rsplit("/", 1)[-1]
            matched = fnmatch.fnmatch(rel, pat) if "/" in pat else fnmatch.fnmatch(base, pat)
            if matched and rel not in entry_points:
                entry_points.append(rel)

    # Source roots by discovery mode.
    source_roots: list[dict] = []
    if discovery_mode == "build-cs":
        seen: set[tuple[str, str]] = set()
        for rel in files_rel:
            if not rel.endswith(".Build.cs"):
                continue
            name = rel.rsplit("/", 1)[-1]
            parent = rel.rsplit("/", 1)[0] if "/" in rel else "."
            module = name[: -len(".Build.cs")]
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
        "root":              str(root),
        "profile":           profile,
        "total_files":       total_files,
        "total_lines":       total_lines,
        "languages":         languages,
        "directory_tree":    directory_tree,
        "entry_points":      entry_points,
        "source_roots":      source_roots,
        "files_rel":         files_rel,
        "files_rel_source":  files_rel_source,
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
