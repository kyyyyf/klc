#!/usr/bin/env python3
"""init.py — first-time bootstrap.

Runs the pipeline:

  1. structural scan  (core/skills/file_scanner.py)       — always
  2. MCP hint         (advisory)                          — always
  3. dep graph        (core/skills/dep_graph.py)          — always
  3b. module SET      (core/skills/modules_build.py)      — always (KLC-074:
                       deterministic; replaces the retired LLM decompose agent)
  4. LLM agents       (inventory → docgen)                — opt-in (annotation only)
  5. record baseline sha (--finalize or --scan-only)

Modes
-----
  (default)      Print agent instructions for manual paste into Claude Code.
  --scan-only    Run only the deterministic steps (1-3) and record the
                 baseline SHA. No LLM calls. Produces structural.json,
                 depgraph.json, and .last-run. Useful for CI or when the
                 project already has CLAUDE.md files.
  --auto         Run all LLM agents automatically via core/skills/runner.py
                 (requires config/models.yml). Same as before.
  --finalize     Record current HEAD as the baseline after the LLM
                 agents have been run manually.

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
from _paths import (  # noqa: E402
    project_root, klc_dir, klc_index_dir, klc_logs_dir,
)
from module_edges import aggregate_module_edges  # noqa: E402


def log(msg: str) -> None:
    print(f"[init] {msg}")


def die(msg: str) -> int:
    sys.stderr.write(f"[init][err] {msg}\n")
    return 1


# KLC-074: the `decompose` LLM agent is retired from the pipeline. The module SET is
# now built deterministically by core/skills/modules_build.py (see _build_modules
# below), closing the last LLM-derived piece of the planning index. inventory + docgen
# remain LLM-annotation steps; both run AFTER modules.json exists.
_INDEXING_AGENTS = (
    ("inventory",
     "core/agents/inventory.md",
     ".klc/index/inventory.json",
     "INVENTORY_OK"),
    ("docgen",
     "core/agents/docgen.md",
     "CLAUDE.md (root + per-module)",
     "DOCGEN_OK"),
)


def _finalize(index_dir: Path) -> int:
    r = subprocess.run(["git", "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        return die("git rev-parse HEAD failed — is this a git repo?")
    head = r.stdout.strip()
    (index_dir / ".last-run").write_text(head + "\n", encoding="utf-8")
    # Clear any stale.json left from a previous update cycle
    stale = index_dir / "stale.json"
    if stale.exists():
        stale.unlink()
    log(f"Recorded {head} in .klc/index/.last-run")

    # Print next steps
    log("")
    log("Next steps:")
    log("  1. klc setup    # detect languages, show required tool install commands")
    log("  2. klc doctor   # verify installation health")

    return 0


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


def _build_modules(index_dir: Path) -> None:
    """KLC-074: build modules.json DETERMINISTICALLY via core/skills/modules_build.py,
    replacing the retired LLM `decompose` agent. Clusters the full tracked-file listing
    by directory (non-code dirs included) so nothing orphans. Degrade-not-fail: a
    non-zero exit is logged and the existing modules.json (if any) is left untouched —
    a failed build must never abort init/update or clobber a good module set."""
    script = FRAMEWORK_ROOT / "core" / "skills" / "modules_build.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script),
             "--in-structural", str(index_dir / "structural.json"),
             "--in-depgraph", str(index_dir / "depgraph.json"),
             "--out-modules", str(index_dir / "modules.json")],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            log(f"  modules_build degraded (exit {r.returncode}); "
                f"keeping existing modules.json")
            if r.stderr:
                sys.stderr.write(r.stderr)
        else:
            log(f"  modules.json (deterministic): {r.stdout.strip()}")
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"  modules_build failed ({e}); keeping existing modules.json")


def _validate_modules(index_dir: Path) -> None:
    """KLC-074: cross-check modules.json with planning_validate.py (self-consistency of
    the membership map through the single resolver, PLUS the KLC-071 cross-artifact
    checks against file_roles/module_edges). Advisory / degrade-not-fail — warnings are
    logged, never fatal, so a validation hiccup does not break bootstrap.

    KLC-074 review LOW-1: call this AFTER _build_planning_views so file_roles.json and
    module_edges.json are the CURRENT run's output, not a stale previous copy — the
    cross-artifact eligibility/edge checks then validate fresh data."""
    script = FRAMEWORK_ROOT / "core" / "skills" / "planning_validate.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script),
             "--in-modules", str(index_dir / "modules.json"),
             "--in-file-roles", str(index_dir / "file_roles.json"),
             "--in-module-edges", str(index_dir / "module_edges.json")],
            capture_output=True, text=True, timeout=120,
        )
        report = json.loads(r.stdout) if r.stdout.strip() else {}
        warnings = report.get("warnings") or []
        if warnings:
            log(f"  planning_validate: {len(warnings)} warning(s) "
                f"(advisory): {warnings[0]}")
        else:
            log("  planning_validate: modules.json is self-consistent")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        log(f"  planning_validate skipped ({e})")


def _build_planning_views(index_dir: Path) -> None:
    """KLC-070/KLC-071: build the deterministic planning views (inventory, test_map,
    file_roles, module_edges v2, symbol_usage) in dependency order. Degrade-not-fail —
    a builder that errors is logged and skipped, never aborting init.

    Order: inventory first (independent of modules.json); then test_map, file_roles
    (KLC-071: needs inventory + modules + structural), module_edges, and symbol_usage
    (KLC-071: needs inventory + callgraph, degrades to import-level usage). When
    modules.json / depgraph / callgraph are absent early in bootstrap the builders
    degrade into their own errors[] rather than failing.
    KLC-074: the module SET is now built by _build_modules (modules_build.py) BEFORE
    this runs, so these views consume the deterministic modules.json via the single
    file_to_module() resolver (KLC-070 D-001 / AC-13 is superseded — the LLM decompose
    agent no longer decides membership)."""
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


def _run_scanner(script: Path, out_file: Path, step: str) -> int:
    log(f"{step} {script.name}")
    r = subprocess.run([sys.executable, str(script)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return die(f"{script.name} failed")
    out_file.write_text(r.stdout, encoding="utf-8")
    try:
        json.loads(out_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return die(f"{script.name} produced invalid JSON: {e}")
    log(f"  -> {out_file.relative_to(project_root())}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc init", description=__doc__)
    ap.add_argument("--finalize", action="store_true",
                    help="Record current HEAD as the baseline after the "
                         "LLM agents have finished.")
    ap.add_argument("--scan-only", action="store_true",
                    help="Run only deterministic steps (file_scanner + dep_graph + "
                         "modules_build) and record baseline SHA. No LLM calls.")
    ap.add_argument("--auto", action="store_true",
                    help="Run inventory/docgen automatically via "
                         "core/skills/runner.py (requires config/models.yml).")
    args = ap.parse_args(argv)

    root = project_root()
    os.chdir(root)

    klc_dir().mkdir(parents=True, exist_ok=True)
    index_dir = klc_index_dir()
    index_dir.mkdir(parents=True, exist_ok=True)
    klc_logs_dir().mkdir(parents=True, exist_ok=True)

    log(f"Project root:   {root}")
    log(f"Framework root: {FRAMEWORK_ROOT}")
    log(f"State dir:      {klc_dir()}")

    if args.finalize:
        return _finalize(index_dir)

    # Step 1: structural scan.
    rc = _run_scanner(
        FRAMEWORK_ROOT / "core" / "skills" / "file_scanner.py",
        index_dir / "structural.json",
        "Step 1/3:" if args.scan_only else "Step 1/5:",
    )
    if rc:
        return rc

    # Step 2: MCP bootstrap hint (advisory).
    log("Step 2/3: MCP configuration (advisory)" if args.scan_only
        else "Step 2/5: MCP configuration (advisory)")
    if (root / ".mcp.json").exists():
        log("  .mcp.json present; ast-grep configured.")
    else:
        log("  No project-level .mcp.json found — init will still work without it.")
        log("  When you're ready for ticket work, copy profiles/<profile>/mcp.json")
        log("  to .mcp.json (gives you ast-grep).")

    # Step 3: dep graph.
    rc = _run_scanner(
        FRAMEWORK_ROOT / "core" / "skills" / "dep_graph.py",
        index_dir / "depgraph.json",
        "Step 3/3:" if args.scan_only else "Step 3/5:",
    )
    if rc:
        log("  WARN: dep_graph failed; inventory will note this")

    # KLC-074: build the deterministic module SET (replaces the LLM decompose agent).
    # Runs on the scan-only path too, so `init --scan-only` now produces modules.json.
    log("Building deterministic modules.json (modules_build)")
    _build_modules(index_dir)

    # Aggregate module reverse edges from depgraph (non-fatal; no-op if
    # modules.json is absent — e.g. modules_build degraded).
    _aggregate_and_write_module_edges(index_dir)

    # KLC-070: build the deterministic planning views (inventory always; test_map /
    # module_edges degrade if modules.json is not yet present). Runs on the
    # scan-only deterministic path so `init --scan-only` produces inventory.json.
    _build_planning_views(index_dir)

    # KLC-074 review LOW-1: validate modules.json AFTER the views exist so the
    # cross-artifact checks see this run's file_roles/module_edges (advisory).
    _validate_modules(index_dir)

    # --scan-only: record baseline and stop — no LLM needed.
    if args.scan_only:
        rc = _finalize(index_dir)
        if rc:
            return rc
        log("Scan-only init complete. No LLM agents were run.")
        log("CLAUDE.md files will be generated on first ticket (klc intake)")
        log("or run `klc init --auto` to generate them now.")
        print("INIT_SCAN_OK")
        return 0

    # Steps 4-5: LLM agents.
    if args.auto:
        sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
        from runner import run_agent  # noqa: E402

        log("Step 4/5: running indexing agents via core/skills/runner.py "
            "(inventory + docgen; module SET already built deterministically)")
        for name, prompt_rel, out_desc, trailer in _INDEXING_AGENTS:
            prompt_path = FRAMEWORK_ROOT / prompt_rel
            out_path = index_dir / f"_{name}.out.md"
            log(f"  [{name}] prompt={prompt_rel} → {out_path.relative_to(root)}")
            rc = run_agent(
                phase_id="indexing",
                prompt_path=prompt_path,
                out_path=out_path,
            )
            if rc != 0:
                return die(
                    f"agent {name!r} failed (exit {rc}); "
                    f"see {out_path.relative_to(root)}"
                )
            text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
            if trailer and trailer not in text:
                return die(
                    f"agent {name!r} did not emit trailer {trailer!r}; "
                    f"inspect {out_path.relative_to(root)}"
                )
            log(f"  [{name}] {trailer} ✓")
        # modules.json was already built deterministically above; re-aggregate
        # reverse edges and rebuild the planning views so they see the module set.
        _aggregate_and_write_module_edges(index_dir)
        _build_planning_views(index_dir)
        _validate_modules(index_dir)  # LOW-1: after views are refreshed
        log("Step 5/5: recording baseline sha")
        return _finalize(index_dir)

    log("Step 4/5: run the LLM agents in Claude Code "
        "(module SET already built deterministically by modules_build)")
    for name, prompt, out, ok in _INDEXING_AGENTS:
        print(f"  [{name}]  prompt: {prompt}")
        print(f"           outputs: {out}")
        print(f"           trailer: {ok}")

    log("Step 5/5: record baseline sha after the agents finish")
    log(f"  klc init --finalize     # writes HEAD to {index_dir / '.last-run'}")
    log("init done. Next: run the agents above inside Claude Code.")
    log("")
    log("TIP: for a quick start without LLM, run:")
    log("  klc init --scan-only")
    log("  (generates structural.json + depgraph.json, no CLAUDE.md files)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
