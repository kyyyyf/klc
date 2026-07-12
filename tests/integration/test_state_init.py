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
    """Call state.run(argv) with cwd chdir-ed into `root` (restored after).

    PROJECT_ROOT is popped for the duration so the in-process run resolves the
    repo from cwd (`git rev-parse --show-toplevel`) and can never target an
    ambient real repo pointed at by an inherited PROJECT_ROOT.
    """
    state = _load_state()
    old = os.getcwd()
    old_pr = os.environ.pop("PROJECT_ROOT", None)
    try:
        os.chdir(root)
        return state.run(argv)
    finally:
        os.chdir(old)
        if old_pr is not None:
            os.environ["PROJECT_ROOT"] = old_pr


def _run_in_patched(root: Path, argv, patch):
    """Like `_run_in` but applies `patch(state_module)` before running so tests
    can inject failures into the *same* module instance that executes run()."""
    state = _load_state()
    patch(state)
    old = os.getcwd()
    old_pr = os.environ.pop("PROJECT_ROOT", None)
    try:
        os.chdir(root)
        return state.run(argv)
    finally:
        os.chdir(old)
        if old_pr is not None:
            os.environ["PROJECT_ROOT"] = old_pr


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


# --- AC-1: origin already has a klc-state branch ----------------------------


def _make_origin_with_state(tmp_path: Path, files: dict | None = None) -> Path:
    """Build a bare 'origin' repo that already carries a klc-state branch.

    `files` maps repo-relative paths to contents (default: tickets/origin.txt).
    Returns the bare repo path."""
    if files is None:
        files = {"tickets/origin.txt": "ORIGIN-TICKET"}
    build = tmp_path / "build"
    build.mkdir()
    _init_repo(build)
    # orphan klc-state branch with ticket file(s)
    _git(["checkout", "--orphan", "klc-state"], build)
    _git(["rm", "-rf", "--cached", "."], build, check=False)
    (build / "a.txt").unlink()
    for rel, content in files.items():
        p = build / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(["add", "-A"], build)
    _git(["commit", "-m", "klc-state root"], build)
    _git(["checkout", "main"], build)

    bare = tmp_path / "origin.git"
    _git(["clone", "--bare", str(build), str(bare)], tmp_path)
    return bare


def test_state_init_tracks_origin_and_preserves_local(tmp_path):
    origin = _make_origin_with_state(tmp_path)

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["fetch", "origin"], root)

    # local pre-existing ticket must survive
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("LOCAL-TICKET", encoding="utf-8")

    rc = _run_in(root, ["init"])
    assert rc == 0, "state init should exit 0 when origin has klc-state"

    # .klc worktree tracks origin/klc-state
    upstream = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], root / ".klc", check=False
    ).stdout.strip()
    assert upstream == "origin/klc-state", f"upstream not tracking origin: {upstream!r}"

    # both origin-provided and local ticket files present
    assert (root / ".klc" / "tickets" / "origin.txt").read_text(encoding="utf-8") == "ORIGIN-TICKET"
    assert (root / ".klc" / "tickets" / "local.txt").read_text(encoding="utf-8") == "LOCAL-TICKET"


# --- dispatcher wiring ------------------------------------------------------


def test_klc_state_init_dispatched(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    env = {**os.environ, "PROJECT_ROOT": str(root)}
    result = subprocess.run(
        [sys.executable, str(KLC), "state", "init"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"dispatch failed: {result.stderr}"
    assert str((root / ".klc").resolve()) in _worktree_paths(root)


# --- M3: repo root honored from a subdirectory ------------------------------


def test_state_init_from_subdirectory_targets_repo_root(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    sub = root / "a" / "b"
    sub.mkdir(parents=True)

    rc = _run_in(sub, ["init"])
    assert rc == 0, "state init should exit 0 when run from a subdirectory"

    # .klc must be created at the REPO ROOT, never inside the subdirectory
    assert (root / ".klc").is_dir(), ".klc must be materialized at the repo root"
    assert not (sub / ".klc").exists(), ".klc must NOT be created in the subdirectory"
    assert str((root / ".klc").resolve()) in _worktree_paths(root)


# --- M4(a): collision — local content wins over origin's klc-state ----------


def test_state_init_collision_local_wins(tmp_path):
    # origin's klc-state carries tickets/dup.txt with ORIGIN content
    origin = _make_origin_with_state(tmp_path, {"tickets/dup.txt": "ORIGIN-CONTENT"})

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["fetch", "origin"], root)

    # local pre-existing tickets/dup.txt with DIFFERENT content
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "dup.txt").write_text("LOCAL-CONTENT", encoding="utf-8")

    assert _run_in(root, ["init"]) == 0

    # local content must survive the collision
    assert (root / ".klc" / "tickets" / "dup.txt").read_text(encoding="utf-8") == "LOCAL-CONTENT"


# --- M4(b) + H1: failure-restore, teardown, no false idempotent success -----


def _inject_commit_failure(state):
    """Monkeypatch _git so the orphan root `commit` fails (simulates e.g. a
    commit hook / gpg failure) after the .klc worktree already exists."""
    real = state._git

    def fake(args, cwd, *, check=True):
        if "commit" in args:
            raise subprocess.CalledProcessError(
                1, ["git", *args], stderr="injected commit failure"
            )
        return real(args, cwd, check=check)

    state._git = fake


def test_state_init_failure_restores_local_and_reports_error(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    # local ticket content that must not be lost on failure
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("PRECIOUS", encoding="utf-8")

    rc = _run_in_patched(root, ["init"], _inject_commit_failure)
    assert rc == 1, "a mid-init failure must report failure (non-zero)"

    # original content is restored in place, NOT stranded in the backup dir
    assert (root / ".klc" / "tickets" / "local.txt").read_text(encoding="utf-8") == "PRECIOUS"
    assert not (root / ".klc.init-bak").exists(), "backup must not be left stranded"
    # the partial worktree must have been torn down (not a registered worktree)
    assert str((root / ".klc").resolve()) not in _worktree_paths(root)


def test_state_init_no_false_idempotent_success_after_partial(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("PRECIOUS", encoding="utf-8")

    # first run fails mid-init
    assert _run_in_patched(root, ["init"], _inject_commit_failure) == 1

    # a subsequent CLEAN run must actually complete, not falsely report success
    rc = _run_in(root, ["init"])
    assert rc == 0, "recovery run should complete init"
    assert str((root / ".klc").resolve()) in _worktree_paths(root)
    assert (root / ".klc" / "tickets" / "local.txt").read_text(encoding="utf-8") == "PRECIOUS"
    # branch really exists with the orphan root commit
    assert "klc-state" in _git(["branch", "--list", "klc-state"], root).stdout


def test_state_init_refuses_when_worktree_present_but_backup_stranded(tmp_path):
    """Defense-in-depth: a registered .klc worktree AND a leftover .klc.init-bak
    means a prior init did not complete — must not report success."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    assert _run_in(root, ["init"]) == 0  # real worktree now present

    # simulate a stranded backup from an interrupted earlier run
    bak = root / ".klc.init-bak"
    (bak / "tickets").mkdir(parents=True)
    (bak / "tickets" / "old.txt").write_text("STRANDED", encoding="utf-8")

    rc = _run_in(root, ["init"])
    assert rc != 0, "must not report idempotent success while a backup is stranded"
    # the stranded backup is preserved, not silently discarded
    assert (bak / "tickets" / "old.txt").read_text(encoding="utf-8") == "STRANDED"


# --- L6: pre-existing backup is never destroyed -----------------------------


def test_state_init_refuses_to_clobber_existing_backup(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    # a stranded backup from a prior interrupted run (the only copy of old data)
    bak = root / ".klc.init-bak"
    (bak / "tickets").mkdir(parents=True)
    (bak / "tickets" / "old.txt").write_text("ONLY-COPY", encoding="utf-8")

    # plus fresh local content in .klc
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "new.txt").write_text("NEW", encoding="utf-8")

    rc = _run_in(root, ["init"])
    assert rc != 0, "must refuse rather than overwrite an existing backup"
    # the pre-existing backup is intact
    assert (bak / "tickets" / "old.txt").read_text(encoding="utf-8") == "ONLY-COPY"


# --- L7: merge-back tolerates symlinks and dir/file type clashes -------------


def test_state_init_merge_back_preserves_dangling_symlink(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "real.txt").write_text("REAL", encoding="utf-8")
    # a dangling symlink — copytree(symlinks=False) would raise on this
    os.symlink("does-not-exist", tdir / "dangling")

    assert _run_in(root, ["init"]) == 0

    link = root / ".klc" / "tickets" / "dangling"
    assert link.is_symlink(), "symlink must be preserved as a symlink"
    assert os.readlink(link) == "does-not-exist"
    assert (root / ".klc" / "tickets" / "real.txt").read_text(encoding="utf-8") == "REAL"


def test_state_init_merge_back_dir_vs_file_clash_local_wins(tmp_path):
    # origin's klc-state has `x` as a DIRECTORY (x/inner.txt)
    origin = _make_origin_with_state(tmp_path, {"x/inner.txt": "ORIGIN-DIR"})

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["fetch", "origin"], root)

    # locally, `x` is a FILE (type clash with origin's directory)
    klc = root / ".klc"
    klc.mkdir()
    (klc / "x").write_text("LOCAL-FILE", encoding="utf-8")

    assert _run_in(root, ["init"]) == 0

    # local file must win the type clash
    assert (klc / "x").is_file(), "local file must replace origin's directory"
    assert (klc / "x").read_text(encoding="utf-8") == "LOCAL-FILE"


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
