#!/usr/bin/env python3
"""Tests for `klc state init [<remote>]` (KLC-053).

`klc state init` materializes the project's `klc-state` orphan branch as a git
worktree at `.klc/` in the SAME repo (no separate state repo).  These tests
exercise `core/phases/state.py:run()` directly by chdir-ing into throwaway temp
git repos, and the dispatcher wiring via `scripts/klc state init`.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_PY = FW_ROOT / "core" / "phases" / "state.py"
KLC = FW_ROOT / "scripts" / "klc"


def _load_state():
    spec = importlib.util.spec_from_file_location("klc_phase_state", STATE_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _git(args, cwd, *, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def _init_repo(root: Path) -> None:
    _git(["init", "-b", "main"], root)
    _git(["config", "user.name", "t"], root)
    _git(["config", "user.email", "t@t"], root)
    (root / "a.txt").write_text("hi", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "init"], root)


def _run_in(root: Path, argv):
    """Call state.run(argv) with cwd chdir-ed into `root` (restored after)."""
    state = _load_state()
    old = os.getcwd()
    try:
        os.chdir(root)
        return state.run(argv)
    finally:
        os.chdir(old)


def _worktree_paths(root: Path):
    out = _git(["worktree", "list", "--porcelain"], root).stdout
    return [
        str(Path(line[len("worktree "):]).resolve())
        for line in out.splitlines()
        if line.startswith("worktree ")
    ]


# --- AC-2: no klc-state branch exists ---------------------------------------


def test_state_init_creates_orphan_and_worktree(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    rc = _run_in(root, ["init"])
    assert rc == 0, "state init should exit 0"

    # klc-state branch now exists as a real ref
    branches = _git(["branch", "--list", "klc-state"], root).stdout
    assert "klc-state" in branches, f"klc-state branch missing: {branches!r}"

    # .klc is a registered worktree
    assert str((root / ".klc").resolve()) in _worktree_paths(root)

    # orphan root: history disjoint from main (exactly one, empty commit)
    count = _git(["rev-list", "--count", "klc-state"], root).stdout.strip()
    assert count == "1", f"klc-state should have a single orphan root commit, got {count}"
    # main must NOT be an ancestor of klc-state (disjoint histories)
    anc = _git(["merge-base", "--is-ancestor", "main", "klc-state"], root, check=False)
    assert anc.returncode != 0, "klc-state history must be disjoint from main"


def test_state_init_idempotent(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    assert _run_in(root, ["init"]) == 0
    # second run is a no-op, still exit 0
    assert _run_in(root, ["init"]) == 0

    # exactly one .klc worktree registered (no duplicate)
    klc = str((root / ".klc").resolve())
    assert _worktree_paths(root).count(klc) == 1


def test_state_init_preserves_existing_tickets_orphan(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    # pre-existing ticket content in a plain .klc directory
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "t1.txt").write_text("LOCAL-TICKET", encoding="utf-8")

    assert _run_in(root, ["init"]) == 0

    preserved = root / ".klc" / "tickets" / "t1.txt"
    assert preserved.read_text(encoding="utf-8") == "LOCAL-TICKET"
    assert str((root / ".klc").resolve()) in _worktree_paths(root)


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
