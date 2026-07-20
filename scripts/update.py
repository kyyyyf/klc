#!/usr/bin/env python3
"""update.py — deterministic incremental refresh after commits.

Runs the deterministic pipeline:
  1. git diff since .last-run → changed-files.txt
  2. file_scanner → structural.json (refresh)
  3. dep_graph    → depgraph.json (refresh)
  4. per_module_hash diff → stale.json (which modules need doc regen)
  5. Write stale.json; advance .last-run

No LLM is called. Designed to run in a post-commit hook (~1-3s).

When modules are stale:
  klc intake will warn the operator.
  To regenerate docs for stale modules run:
    klc update --regen        (skeleton CLAUDE.md, no LLM)
    klc update --regen --llm  (one LLM call per stale module, expensive)

Per-project state lives in $PROJECT_ROOT/.klc/.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
from _paths import project_root, klc_index_dir, klc_logs_dir  # noqa: E402
from module_edges import aggregate_module_edges  # noqa: E402
import module_membership as _mm  # noqa: E402  (KLC-066: the one resolver)


def log(msg: str) -> None:
    print(f"[update] {msg}")


def err(msg: str) -> int:
    sys.stderr.write(f"[update][err] {msg}\n")
    return 1


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #

def _git_head(root: Path) -> str:
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else ""


def _changed_files(root: Path, last: str, head: str) -> list[str]:
    r = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only",
         "--diff-filter=ACMRD", last, head],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# deterministic scan helpers
# --------------------------------------------------------------------------- #

def _run_scanner(script: Path, out_file: Path) -> int:
    r = subprocess.run([sys.executable, str(script)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return 1
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[update] {script.name} produced invalid JSON: {e}\n")
        return 1
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return 0


def _compute_stale(index_dir: Path, changed: list[str]) -> dict:
    """Given changed file list, return stale module info.

    Loads modules.json, maps changed files to modules, walks depended_by
    for transitive closure, returns:
      {"stale_modules": [...], "changed_files": N, "total_modules": N}
    """
    modules_file = index_dir / "modules.json"
    if not modules_file.exists():
        return {"stale_modules": [], "changed_files": len(changed), "total_modules": 0}

    try:
        raw = json.loads(modules_file.read_text(encoding="utf-8"))
        modules: list[dict] = raw.get("modules", raw) if isinstance(raw, dict) else raw
        if not isinstance(modules, list):
            raise ValueError("unexpected modules.json shape")
    except (json.JSONDecodeError, OSError, ValueError, AttributeError):
        return {"stale_modules": [], "changed_files": len(changed), "total_modules": 0}

    total = len(modules)
    if not changed or not modules:
        return {"stale_modules": [], "changed_files": len(changed), "total_modules": total}

    # KLC-066: map changed files to modules through the single file_to_module()
    # resolver (the private path→module copy is deleted) so stale detection sees
    # exactly the module set scope_delta / module_edges / diff-modules see. A
    # shared file marks every module in its member_of stale.
    modules_data = raw if isinstance(raw, dict) else {"modules": modules}
    directly_stale: set[str] = set()
    for f in changed:
        directly_stale.update(_mm.file_to_module(f, modules_data)["member_of"])

    # Transitive closure via depended_by
    name_to_mod = {m["name"]: m for m in modules}
    visited: set[str] = set(directly_stale)
    queue = list(directly_stale)
    while queue:
        mname = queue.pop()
        mod = name_to_mod.get(mname, {})
        for dep in (mod.get("depended_by") or []):
            if dep not in visited:
                visited.add(dep)
                queue.append(dep)

    # Fallback: if >20% of tracked files changed, mark everything stale
    tracked_files = sum(len(m.get("files") or []) for m in modules) or 1
    if len(changed) / tracked_files > 0.2:
        visited = {m["name"] for m in modules}
        log(f"  >20% of tracked files changed — marking all {total} modules stale")

    return {
        "stale_modules": sorted(visited),
        "changed_files": len(changed),
        "total_modules": total,
    }


# --------------------------------------------------------------------------- #
# skeleton CLAUDE.md regen (no LLM)
# --------------------------------------------------------------------------- #

def _regen_skeleton(index_dir: Path, stale_names: list[str]) -> int:
    """Regenerate CLAUDE.md skeleton for stale modules without LLM.
    Delegates to module-writer.py --only <names>."""
    if not stale_names:
        log("No stale modules to regenerate.")
        return 0
    writer = FRAMEWORK_ROOT / "core" / "skills" / "module-writer.py"
    if not writer.exists():
        return err(f"module-writer.py not found at {writer}")
    names_arg = ",".join(stale_names)
    log(f"Regenerating skeleton CLAUDE.md for: {names_arg}")
    r = subprocess.run(
        [sys.executable, str(writer), "--only", names_arg],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return err("module-writer.py failed")
    log(r.stdout.strip())
    return 0


# --------------------------------------------------------------------------- #
# module edge aggregation
# --------------------------------------------------------------------------- #

def _aggregate_and_write_module_edges(index_dir: Path) -> None:
    """Read modules.json + depgraph.json, write back with populated
    depends_on/depended_by. No-ops silently if either file is missing."""
    modules_file = index_dir / "modules.json"
    depgraph_file = index_dir / "depgraph.json"
    if not modules_file.exists():
        return
    try:
        modules_data = json.loads(modules_file.read_text(encoding="utf-8"))
        if not isinstance(modules_data, dict):
            modules_data = {"modules": modules_data}
    except (json.JSONDecodeError, OSError):
        return
    try:
        depgraph = json.loads(depgraph_file.read_text(encoding="utf-8")) if depgraph_file.exists() else {}
    except (json.JSONDecodeError, OSError):
        depgraph = {}
    updated = aggregate_module_edges(modules_data, depgraph)
    modules_file.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    n = len(updated.get("modules", []))
    log(f"  reverse edges written for {n} module(s)")


def _build_planning_views(index_dir: Path) -> None:
    """KLC-070/KLC-071: refresh the deterministic planning views (inventory, test_map,
    file_roles, module_edges v2, symbol_usage) after an incremental update.
    Degrade-not-fail. Does NOT run
    modules_build — the module SET is unchanged (D-001 / AC-13); the views consume
    the current modules.json via the file_to_module() resolver."""
    skills = FRAMEWORK_ROOT / "core" / "skills"
    views = (
        ("inventory",    skills / "deterministic_inventory.py",
         ["--out", str(index_dir / "inventory.json")]),
        ("test_map",     skills / "test_map.py",
         ["--out", str(index_dir / "test_map.json")]),
        # KLC-071: file_roles depends on inventory (built above) + modules + structural.
        ("file_roles",   skills / "file_roles.py",
         ["--out", str(index_dir / "file_roles.json")]),
        ("module_edges", skills / "module_edges.py",
         ["--edges-only", "--out-edges", str(index_dir / "module_edges.json")]),
        # KLC-071: symbol_usage depends on inventory + callgraph (degrades to imports).
        ("symbol_usage", skills / "symbol_usage.py",
         ["--out", str(index_dir / "symbol_usage.json")]),
    )
    for name, script, extra in views:
        try:
            r = subprocess.run([sys.executable, str(script), *extra],
                               capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                log(f"  planning view '{name}' degraded (exit {r.returncode})")
            else:
                log(f"  planning view: {name}")
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"  planning view '{name}' failed ({e})")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc update", description=__doc__)
    ap.add_argument("--regen", action="store_true",
                    help="Regenerate skeleton CLAUDE.md for stale modules "
                         "(deterministic, no LLM).")
    ap.add_argument("--force", action="store_true",
                    help="Run even if HEAD == .last-run (useful after manual edits).")
    args = ap.parse_args(argv)

    root = project_root()
    os.chdir(root)

    index_dir = klc_index_dir()
    index_dir.mkdir(parents=True, exist_ok=True)
    klc_logs_dir().mkdir(parents=True, exist_ok=True)

    last_file = index_dir / ".last-run"
    if not last_file.exists():
        return err(".klc/index/.last-run missing; run `klc init` first")
    last = last_file.read_text(encoding="utf-8").strip()

    head = _git_head(root)
    if not head:
        return err("git rev-parse HEAD failed — is this a git repo?")

    if last == head and not args.force:
        print("UPDATE_NOOP")
        return 0

    log(f"Change window: {last[:8]}..{head[:8]}")
    changed = _changed_files(root, last, head)

    # Filter out .klc/ internal files — they are not project source
    changed = [f for f in changed if not f.startswith(".klc/")]

    changed_file = index_dir / "changed-files.txt"
    changed_file.write_text("\n".join(changed) + "\n", encoding="utf-8")
    log(f"Changed source files: {len(changed)}")

    # Step 1: re-scan structure
    log("Step 1/3: file_scanner")
    rc = _run_scanner(
        FRAMEWORK_ROOT / "core" / "skills" / "file_scanner.py",
        index_dir / "structural.json",
    )
    if rc:
        return err("file_scanner failed")

    # Step 2: re-scan dep graph (non-fatal)
    log("Step 2/4: dep_graph")
    rc = _run_scanner(
        FRAMEWORK_ROOT / "core" / "skills" / "dep_graph.py",
        index_dir / "depgraph.json",
    )
    if rc:
        log("  WARN: dep_graph failed; stale detection may be less precise")

    # Step 3: aggregate module-level reverse edges from depgraph (non-fatal)
    log("Step 3/5: aggregating module reverse edges")
    _aggregate_and_write_module_edges(index_dir)

    # KLC-070: refresh the deterministic planning views (non-fatal)
    log("Step 4/5: refreshing planning views (inventory, test_map, file_roles, "
        "module_edges, symbol_usage)")
    _build_planning_views(index_dir)

    # Step 5: compute stale modules
    log("Step 5/5: computing stale modules")
    stale = _compute_stale(index_dir, changed)
    stale_file = index_dir / "stale.json"
    stale_file.write_text(json.dumps(stale, indent=2, ensure_ascii=False),
                          encoding="utf-8")

    n_stale = len(stale["stale_modules"])
    if n_stale:
        log(f"  {n_stale} stale module(s): {', '.join(stale['stale_modules'])}")
    else:
        log("  No modules affected.")

    # Optional: regenerate skeletons
    if args.regen and n_stale:
        rc = _regen_skeleton(index_dir, stale["stale_modules"])
        if rc:
            return rc

    # Advance baseline only after everything succeeded
    last_file.write_text(head + "\n", encoding="utf-8")

    if n_stale:
        print(f"UPDATE_OK {n_stale} module(s) stale"
              + ("" if args.regen else " — run `klc update --regen` to refresh docs"))
    else:
        print("UPDATE_OK no stale modules")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
