#!/usr/bin/env python3
"""init.py — first-time bootstrap.

Port of init.sh. Runs the pipeline:

  1. structural scan (core/skills/file_scanner.py)
  2. dep graph      (core/skills/dep_graph.py)
  3. inventory agent (LLM; paste into Claude Code or run with --auto)
  4. decompose agent (LLM)
  5. docgen agent    (LLM)
  6. record baseline sha (with --finalize)

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


def log(msg: str) -> None:
    print(f"[init] {msg}")


def die(msg: str) -> int:
    sys.stderr.write(f"[init][err] {msg}\n")
    return 1


_INDEXING_AGENTS = (
    ("inventory",
     "core/agents/inventory.md",
     ".klc/index/inventory.json",
     "INVENTORY_OK"),
    ("decompose",
     "core/agents/decompose.md",
     ".klc/index/modules.json",
     "DECOMPOSE_OK"),
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
    log(f"Recorded {head} in .klc/index/.last-run")
    return 0


def _run_scanner(script: Path, out_file: Path, step: str) -> int:
    log(f"{step} {script.name}")
    r = subprocess.run([sys.executable, str(script)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return die(f"{script.name} failed")
    out_file.write_text(r.stdout, encoding="utf-8")
    # Sanity: output must be valid JSON.
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
                         "three LLM agents have finished.")
    ap.add_argument("--auto", action="store_true",
                    help="Run inventory/decompose/docgen automatically via "
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
        "Step 1/5:",
    )
    if rc:
        return rc

    # Step 2: MCP bootstrap hint (advisory).
    log("Step 2/5: MCP configuration (advisory)")
    if (root / ".mcp.json").exists():
        log("  .mcp.json present; ast-grep (and optionally Serena) configured.")
    else:
        log("  No project-level .mcp.json found — init will still work without it.")
        log("  When you're ready for ticket work, copy profiles/<profile>/mcp.json")
        log("  to .mcp.json (gives you ast-grep + Serena).")

    # Step 3: dep graph.
    rc = _run_scanner(
        FRAMEWORK_ROOT / "core" / "skills" / "dep_graph.py",
        index_dir / "depgraph.json",
        "Step 3/5:",
    )
    if rc:
        # dep-graph non-fatal — log and proceed.
        log("  WARN: dep_graph failed; inventory will note this")

    # Steps 4-5: LLM agents.
    if args.auto:
        sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
        from runner import run_agent  # noqa: E402

        log("Step 4/5: running indexing agents via core/skills/runner.py")
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
        log("Step 5/5: recording baseline sha")
        return _finalize(index_dir)

    log("Step 4/5: run the three LLM agents in Claude Code")
    for name, prompt, out, ok in _INDEXING_AGENTS:
        print(f"  [{name}]  prompt: {prompt}")
        print(f"           outputs: {out}")
        print(f"           trailer: {ok}")

    log("Step 5/5: record baseline sha after the agents finish")
    log(f"  klc init --finalize     # writes HEAD to {index_dir / '.last-run'}")
    log("init done. Next: run the three agents above inside Claude Code.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
