#!/usr/bin/env python3
"""update.py — incremental refresh after commits.

Port of update.sh. Computes the change window between the recorded
last-run SHA and the current HEAD, writes the changed-file list, and
prints the periodic agent prompt for the operator to paste into
Claude Code (or, with `--auto`, runs it through core/skills/runner.py
once that lands).

Per-project state lives in $PROJECT_ROOT/.klc/.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
from _paths import project_root, klc_index_dir, klc_logs_dir  # noqa: E402


def log(msg: str) -> None:
    print(f"[update] {msg}")


def err(msg: str) -> int:
    sys.stderr.write(f"[update][err] {msg}\n")
    return 1


def _git_head() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def _changed_files(last: str, head: str) -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRD", last, head],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc update", description=__doc__)
    ap.add_argument("--auto", action="store_true",
                    help="Run the periodic agent via core/skills/runner.py "
                         "(requires config/models.yml).")
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

    head = _git_head()
    if not head:
        return err("git rev-parse HEAD failed — is this a git repo?")

    if last == head:
        print("PERIODIC_NOOP")
        return 0

    log(f"Change window: {last}..{head}")
    changed = _changed_files(last, head)
    changed_file = index_dir / "changed-files.txt"
    changed_file.write_text("\n".join(changed) + "\n", encoding="utf-8")
    log(f"Changed files -> {changed_file.relative_to(root)} ({len(changed)} file(s))")

    if args.auto:
        sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
        from runner import run_agent  # noqa: E402

        prompt = FRAMEWORK_ROOT / "core" / "agents" / "periodic.md"
        out_path = index_dir / "_periodic.out.md"
        log(f"Running periodic agent via runner → {out_path.relative_to(root)}")
        rc = run_agent(
            phase_id="indexing",
            prompt_path=prompt,
            out_path=out_path,
        )
        if rc != 0:
            return err(
                f"periodic agent failed (exit {rc}); "
                f"see {out_path.relative_to(root)}"
            )
        text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if "PERIODIC_NOOP" in text:
            print("PERIODIC_NOOP")
            return 0
        if "PERIODIC_OK" not in text:
            return err(
                f"periodic agent produced no PERIODIC_OK / PERIODIC_NOOP trailer; "
                f"inspect {out_path.relative_to(root)}"
            )
        last_file.write_text(head + "\n", encoding="utf-8")
        print("PERIODIC_OK")
        return 0

    log("Now run the periodic agent inside Claude Code:")
    print("  Prompt:")
    print("    Read core/agents/periodic.md and execute it.")
    print("    Inputs:")
    print(f"      - .klc/index/.last-run (SHA: {last})")
    print( "      - .klc/index/changed-files.txt")
    print( "      - .klc/index/inventory.json")
    print( "      - .klc/index/modules.json")
    print(f"    Current HEAD: {head}")
    print(f"    On success, print PERIODIC_OK and overwrite .klc/index/.last-run with {head}.")
    print( "    On no-op, print PERIODIC_NOOP.")
    print("")
    log("After the agent finishes:")
    log(f"  echo {head} > .klc/index/.last-run")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
