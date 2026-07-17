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
sys.path.insert(0, str(_file_dir))  # so `import module_membership` resolves

from core.shared.paths import klc_index_dir, project_root  # noqa: E402
import lifecycle as _lc  # noqa: E402
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)


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


def _bucket_changed(
    files: list[str], modules_data: dict
) -> tuple[list[str], list[str], list[str]]:
    """Route changed files to scope buckets via the single file_to_module()
    resolver (KLC-066 — the private longest-prefix copy is deleted).

    Returns (owned_modules, shared_touched, unknown_files):
      - owned_modules   — primary_module of non-shared changed files. These
                          feed `actual` / `expansion` (the hard-fail path).
      - shared_touched  — member_of of changed *shared* files (primary_module
                          is None). A utility edit must not force every consumer
                          into a hard scope-expansion, so these route to drift
                          (a warning), not expansion (planning_indexer.md
                          §"Правило scope для shared-файлов").
      - unknown_files   — paths that resolve to no module (orphans).
    """
    owned: set[str] = set()
    shared: set[str] = set()
    unknown: list[str] = []
    for f in files:
        res = _mm.file_to_module(f, modules_data)
        if res["is_shared"]:
            shared.update(res["member_of"])
        elif res["primary_module"]:
            owned.add(res["primary_module"])
        else:
            unknown.append(f)
    return sorted(owned), sorted(shared), sorted(unknown)


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
            "shared_touched": [],
            "skipped": "modules.json not found",
        }

    try:
        modules_data: dict = json.loads(modules_path.read_text(encoding="utf-8"))
        if not isinstance(modules_data, dict):
            modules_data = {"modules": modules_data}
    except Exception as exc:
        return {
            "planned": planned, "actual": [], "drift": [], "expansion": [],
            "shared_touched": [],
            "skipped": f"modules.json unreadable: {exc}",
        }

    changed_files = _git_changed_files(project_root())
    # Drop klc's own state directory: `.klc/` holds ticket metadata,
    # the index, and reports — process state, never application scope.
    # It is git-tracked and klc itself dirties it on every phase
    # transition, so counting it would flag a false expansion on every
    # review ack (it maps to the `.klc/tickets/` module).
    changed_files = [f for f in changed_files if not f.startswith(".klc/")]
    if not changed_files:
        return {
            "planned": planned, "actual": [], "drift": [], "expansion": [],
            "shared_touched": [],
            "skipped": "no changed files detected",
        }

    actual, shared_touched, unknown_files = _bucket_changed(changed_files, modules_data)
    planned_set = set(planned)
    drift = sorted(set(actual) - planned_set)
    # Files outside all known module prefixes are treated as expansion.
    # Shared-file modules (shared_touched) are deliberately kept OUT of
    # expansion — a utility edit surfaces as drift (a warning), not a hard-fail,
    # so the author consciously chooses which consumers to add to
    # meta.affected_modules via the existing ack path (KLC-066 AC-5).
    expansion = sorted(set(drift) | set(unknown_files))
    # shared_touched that the author has not already planned surfaces as drift.
    shared_drift = sorted(set(shared_touched) - planned_set)
    drift = sorted(set(drift) | set(shared_drift))
    return {
        "planned": planned,
        "actual": actual,
        "drift": drift,
        "expansion": expansion,
        "shared_touched": sorted(shared_touched),
        "unknown_files": unknown_files,
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
