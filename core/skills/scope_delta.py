#!/usr/bin/env python3
"""scope_delta.py — compare planned scope vs actual diff scope.

API:
    compare(ticket) -> {planned, actual, drift, expansion, skipped}

    planned   — meta.json:affected_modules
    actual    — modules derived from git-changed files via modules.json
    drift     — actual − planned (unplanned modules touched)
    expansion — same as drift (all unplanned = expansion; tier-aware
                classification is a future refinement)
    skipped   — reason string when comparison was not possible

CLI:
    python core/skills/scope_delta.py KLC-XX
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))

from core.shared.paths import klc_index_dir, project_root  # noqa: E402
import lifecycle as _lc  # noqa: E402


def _git_changed_files(root: Path) -> list[str]:
    """Return all files changed in the current branch vs origin/main."""
    files: set[str] = set()

    # Staged + unstaged working-tree changes
    for extra in [["--name-only", "HEAD"], ["--cached", "--name-only"]]:
        try:
            r = subprocess.run(
                ["git", "diff"] + extra,
                capture_output=True, text=True, cwd=str(root), timeout=10
            )
            if r.returncode == 0:
                files.update(f.strip() for f in r.stdout.splitlines() if f.strip())
        except Exception:
            pass

    # Commits on the current branch vs origin/main
    try:
        base_r = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"],
            capture_output=True, text=True, cwd=str(root), timeout=10
        )
        if base_r.returncode == 0 and base_r.stdout.strip():
            base = base_r.stdout.strip()
            r = subprocess.run(
                ["git", "diff", "--name-only", base, "HEAD"],
                capture_output=True, text=True, cwd=str(root), timeout=10
            )
            if r.returncode == 0:
                files.update(f.strip() for f in r.stdout.splitlines() if f.strip())
    except Exception:
        pass

    return sorted(files)


def _files_to_modules(files: list[str], modules: list[dict]) -> list[str]:
    """Map file paths to module names via longest-prefix matching."""
    sorted_mods = sorted(modules, key=lambda m: -len(m.get("path", "")))
    names: set[str] = set()
    for f in files:
        for m in sorted_mods:
            p = m.get("path", "")
            if p and f.startswith(p):
                names.add(m["name"])
                break
    return sorted(names)


def compare(ticket: str) -> dict:
    """Compare planned scope with actual diff scope.

    Returns a dict with keys: planned, actual, drift, expansion, and
    optionally skipped (reason string when check could not run).
    """
    meta = _lc.read_meta(ticket)
    planned: list[str] = meta.get("affected_modules") or []

    modules_path = klc_index_dir() / "modules.json"
    if not modules_path.exists():
        return {
            "planned": planned, "actual": [], "drift": [], "expansion": [],
            "skipped": "modules.json not found",
        }

    try:
        modules: list[dict] = json.loads(
            modules_path.read_text(encoding="utf-8")
        ).get("modules", [])
    except Exception as exc:
        return {
            "planned": planned, "actual": [], "drift": [], "expansion": [],
            "skipped": f"modules.json unreadable: {exc}",
        }

    changed_files = _git_changed_files(project_root())
    if not changed_files:
        return {
            "planned": planned, "actual": [], "drift": [], "expansion": [],
            "skipped": "no changed files detected",
        }

    actual = _files_to_modules(changed_files, modules)
    planned_set = set(planned)
    drift = sorted(set(actual) - planned_set)
    return {
        "planned": planned,
        "actual": actual,
        "drift": drift,
        "expansion": drift,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ticket", help="Ticket key (e.g. KLC-012)")
    args = ap.parse_args()

    result = compare(args.ticket)
    print(json.dumps(result, indent=2))

    if result.get("skipped"):
        sys.stderr.write(f"[scope-delta] skipped: {result['skipped']}\n")
        return 0

    if result["expansion"]:
        sys.stderr.write(
            f"[scope-delta] EXPANSION: {result['expansion']}\n"
            f"  planned={result['planned']}\n"
            f"  actual={result['actual']}\n"
        )
        return 2

    if result["drift"]:
        sys.stderr.write(f"[scope-delta] drift: {result['drift']}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
