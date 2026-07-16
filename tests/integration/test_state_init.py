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
import shutil
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


# --- L5: git version guard for `worktree add --orphan` ----------------------


def _fake_old_git(state):
    state._git_version = lambda cwd: (2, 41, 0)


def test_state_init_guards_old_git_for_orphan(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    rc = _run_in_patched(root, ["init"], _fake_old_git)
    assert rc == 1, "old git must be rejected before touching the repo"
    err = capsys.readouterr().err
    assert "2.42" in err and "orphan" in err, f"unclear version message: {err!r}"
    # nothing was materialized
    assert str((root / ".klc").resolve()) not in _worktree_paths(root)


# --- P2a (r2): ls-remote failure must not be treated as branch-absence ------


def _stub_ls_remote_failure(state):
    """Simulate an unreachable remote: `git ls-remote` exits non-zero."""
    real = state._git

    def fake(args, cwd, *, check=True):
        if args and args[0] == "ls-remote":
            return subprocess.CompletedProcess(
                ["git", "ls-remote"], 128, stdout="",
                stderr="fatal: unable to access remote",
            )
        return real(args, cwd, check=check)

    state._git = fake


def test_state_init_offline_with_tracking_ref_tracks_not_orphans(tmp_path):
    """ls-remote fails but a local origin/klc-state tracking ref exists →
    materialize by tracking the existing branch, never fork a fresh orphan."""
    origin = _make_origin_with_state(tmp_path)  # tickets/origin.txt

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["fetch", "origin"], root)  # creates refs/remotes/origin/klc-state

    origin_sha = _git(["rev-parse", "refs/remotes/origin/klc-state"], root).stdout.strip()

    rc = _run_in_patched(root, ["init"], _stub_ls_remote_failure)
    assert rc == 0, "should materialize by tracking the existing remote branch"

    # tracks origin/klc-state and shares its history (NOT a disjoint new orphan)
    up = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], root / ".klc", check=False
    ).stdout.strip()
    assert up == "origin/klc-state", f"must track origin, got upstream {up!r}"
    head_sha = _git(["rev-parse", "klc-state"], root).stdout.strip()
    assert head_sha == origin_sha, "must reuse existing branch history, not fork an orphan"
    assert (root / ".klc" / "tickets" / "origin.txt").read_text(encoding="utf-8") == "ORIGIN-TICKET"


def test_state_init_offline_without_tracking_ref_refuses(tmp_path, capsys):
    """ls-remote fails and NO local tracking ref exists → refuse with a clear
    error rather than silently creating a fresh orphan that forks state."""
    origin = _make_origin_with_state(tmp_path)

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)  # NOT fetched → no tracking ref

    rc = _run_in_patched(root, ["init"], _stub_ls_remote_failure)
    assert rc == 1, "must refuse when the remote is unreachable and no ref exists"

    err = capsys.readouterr().err.lower()
    assert "reach" in err or "unreachable" in err, f"unclear message: {err!r}"
    # no orphan branch and no worktree were created
    assert "klc-state" not in _git(["branch", "--list", "klc-state"], root).stdout
    assert not (root / ".klc").exists(), ".klc must not be created on a failed lookup"


# --- P2b (r2): idempotency must verify the worktree is on klc-state ----------


def test_state_init_rejects_klc_worktree_on_wrong_branch(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    # register a .klc worktree checked out on a DIFFERENT branch
    _git(["branch", "other"], root)
    _git(["worktree", "add", str(root / ".klc"), "other"], root)

    rc = _run_in(root, ["init"])
    assert rc != 0, "a .klc worktree on the wrong branch must not be 'already initialized'"

    err = capsys.readouterr().err
    assert "klc-state" in err and "other" in err, f"unclear message: {err!r}"


# --- P2a (r3): a symlink-to-dir on the state branch must be replaced, not -----
# ---           followed (local content wins, nothing written outside .klc/) ---


def test_state_init_merge_back_symlink_to_dir_collision_local_wins(tmp_path):
    # origin's klc-state carries `d` as a symlink that escapes .klc/ (`../escape`)
    build = tmp_path / "build"
    build.mkdir()
    _init_repo(build)
    _git(["checkout", "--orphan", "klc-state"], build)
    _git(["rm", "-rf", "--cached", "."], build, check=False)
    (build / "a.txt").unlink()
    os.symlink("../escape", build / "d")
    _git(["add", "-A"], build)
    _git(["commit", "-m", "klc-state with escaping symlink"], build)
    _git(["checkout", "main"], build)
    bare = tmp_path / "origin.git"
    _git(["clone", "--bare", str(build), str(bare)], tmp_path)

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(bare)], root)
    _git(["fetch", "origin"], root)

    # local `.klc/d` is a REAL directory with a ticket — must win the collision
    ldir = root / ".klc" / "d"
    ldir.mkdir(parents=True)
    (ldir / "inner.txt").write_text("LOCAL", encoding="utf-8")
    # the symlink's escape target exists; it must stay empty (no leak outside .klc/)
    escape = root / "escape"
    escape.mkdir()

    assert _run_in(root, ["init"]) == 0

    d = root / ".klc" / "d"
    assert d.is_dir() and not d.is_symlink(), "local dir must replace the escaping symlink"
    assert (d / "inner.txt").read_text(encoding="utf-8") == "LOCAL"
    # nothing was written through the symlink to outside .klc/
    assert list(escape.iterdir()) == [], f"data leaked outside .klc/: {list(escape.iterdir())}"


# --- P2b (r3): an OSError during merge-back must trigger teardown+restore -----


def _inject_mergeback_oserror(state):
    def boom(backup, klc):
        raise OSError("injected merge-back failure")

    state._merge_back = boom


def test_state_init_merge_back_oserror_restores_backup(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("PRECIOUS", encoding="utf-8")

    rc = _run_in_patched(root, ["init"], _inject_mergeback_oserror)
    assert rc == 1, "a filesystem error mid-merge-back must report failure (non-zero)"

    # ticket data restored in place, not stranded in the backup dir
    assert (root / ".klc" / "tickets" / "local.txt").read_text(encoding="utf-8") == "PRECIOUS"
    assert not (root / ".klc.init-bak").exists(), "backup must not be left stranded"
    assert str((root / ".klc").resolve()) not in _worktree_paths(root)


# --- R4-1: single-branch clone must track the current remote tip -------------


def test_state_init_single_branch_clone_tracks_current_tip(tmp_path):
    """In a single-branch clone the fetch refspec covers only `main`, so a bare
    `git fetch origin klc-state` updates FETCH_HEAD but NOT
    refs/remotes/origin/klc-state. init must still materialize the current tip
    (never fail through to orphan / a stale commit)."""
    build = tmp_path / "build"
    build.mkdir()
    _init_repo(build)
    _git(["checkout", "--orphan", "klc-state"], build)
    _git(["rm", "-rf", "--cached", "."], build, check=False)
    (build / "a.txt").unlink()
    (build / "tickets").mkdir()
    (build / "tickets" / "o.txt").write_text("TIP", encoding="utf-8")
    _git(["add", "-A"], build)
    _git(["commit", "-m", "klc-state tip"], build)
    _git(["checkout", "main"], build)
    origin = tmp_path / "origin.git"
    _git(["clone", "--bare", str(build), str(origin)], tmp_path)

    proj = tmp_path / "proj"
    _git(["clone", "--single-branch", "--branch", "main", str(origin), str(proj)], tmp_path)
    _git(["config", "user.name", "t"], proj)
    _git(["config", "user.email", "t@t"], proj)
    # sanity: this clone tracks only main
    assert _git(["config", "--get-all", "remote.origin.fetch"], proj).stdout.strip() == \
        "+refs/heads/main:refs/remotes/origin/main"

    rc = _run_in(proj, ["init"])
    assert rc == 0, "single-branch clone must materialize klc-state, not fail/orphan"

    # materialized the CURRENT remote tip and tracks origin (not a fresh orphan)
    assert (proj / ".klc" / "tickets" / "o.txt").read_text(encoding="utf-8") == "TIP"
    up = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], proj / ".klc", check=False
    ).stdout.strip()
    assert up == "origin/klc-state", f"must track origin, got {up!r}"
    origin_tip = _git(["ls-remote", str(origin), "klc-state"], proj).stdout.split()[0]
    head = _git(["rev-parse", "klc-state"], proj).stdout.strip()
    assert head == origin_tip, "must track the origin tip, not fork a disjoint orphan"


# --- R4-2: a nested `.git` in preserved `.klc/` must not clobber worktree meta -


def test_state_init_preserved_nested_git_does_not_clobber_worktree(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    # pre-existing `.klc/` that is ITSELF a git repo (has a `.git` directory)
    klc = root / ".klc"
    (klc / "tickets").mkdir(parents=True)
    (klc / "tickets" / "t.txt").write_text("LOCAL", encoding="utf-8")
    _git(["init", "-b", "nested"], klc)
    _git(["config", "user.name", "n"], klc)
    _git(["config", "user.email", "n@n"], klc)
    _git(["add", "-A"], klc)
    _git(["commit", "-m", "nested repo"], klc)
    assert (klc / ".git").is_dir()  # nested repo before init

    rc = _run_in(root, ["init"])
    assert rc == 0

    # `.klc/.git` must be the worktree pointer FILE, not the nested repo dir
    assert (klc / ".git").is_file(), ".klc/.git must be the worktree pointer, not a nested repo"
    # git inside `.klc/` resolves to THIS repo's klc-state worktree
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], klc).stdout.strip() == "klc-state"
    # local ticket content was still preserved
    assert (klc / "tickets" / "t.txt").read_text(encoding="utf-8") == "LOCAL"


# --- R4-3: a removed-but-unpruned worktree must re-materialize ----------------


def test_state_init_rematerializes_after_worktree_dir_removed(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    assert _run_in(root, ["init"]) == 0
    assert (root / ".klc").is_dir()

    # remove the worktree directory on disk but leave it registered (unpruned)
    shutil.rmtree(root / ".klc")
    assert not (root / ".klc").exists()
    # git still lists it (as a prunable/stale registration)
    assert str((root / ".klc").resolve()) in _worktree_paths(root)

    # init must RE-materialize, not report a false idempotent success
    rc = _run_in(root, ["init"])
    assert rc == 0
    assert (root / ".klc").is_dir(), ".klc must be re-created on disk, not a no-op"
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], root / ".klc").stdout.strip() == "klc-state"


# --- r4-review #1: a LOCKED removed worktree must still re-materialize --------


def test_state_init_rematerializes_after_locked_worktree_dir_removed(tmp_path):
    """A locked worktree survives `git worktree prune`, so the stale-worktree
    fallback must force-remove it (`-f -f`) — a single `--force` is refused for a
    locked tree, leaving a false idempotent success while `.klc/` is gone."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    assert _run_in(root, ["init"]) == 0
    assert (root / ".klc").is_dir()

    # lock the worktree, then remove its directory on disk
    _git(["worktree", "lock", str(root / ".klc")], root)
    shutil.rmtree(root / ".klc")
    assert not (root / ".klc").exists()
    # prune cannot drop a locked worktree → it stays registered
    assert str((root / ".klc").resolve()) in _worktree_paths(root)

    rc = _run_in(root, ["init"])
    assert rc == 0
    assert (root / ".klc").is_dir(), "locked+removed worktree must be re-materialized"
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], root / ".klc").stdout.strip() == "klc-state"


# --- r4-review #2: a force-pushed/recreated remote tip must win (forced fetch) -


def test_state_init_force_fetches_recreated_remote_tip(tmp_path):
    """If `klc-state` was recreated with rewritten (non-fast-forward) history, a
    non-forced fetch is rejected and the stale tracking ref would be checked out.
    init must force-update the tracking ref so it materializes the NEW tip."""
    build = tmp_path / "build"
    build.mkdir()
    _init_repo(build)
    _git(["checkout", "--orphan", "klc-state"], build)
    _git(["rm", "-rf", "--cached", "."], build, check=False)
    (build / "a.txt").unlink()
    (build / "tickets").mkdir()
    (build / "tickets" / "o.txt").write_text("OLD", encoding="utf-8")
    _git(["add", "-A"], build)
    _git(["commit", "-m", "old klc-state"], build)
    _git(["checkout", "main"], build)

    origin = tmp_path / "origin.git"
    _git(["clone", "--bare", str(build), str(origin)], tmp_path)

    proj = tmp_path / "proj"
    _git(["clone", str(origin), str(proj)], tmp_path)
    _git(["config", "user.name", "t"], proj)
    _git(["config", "user.email", "t@t"], proj)
    # full clone seeded the (soon-to-be-stale) remote-tracking ref at OLD
    old_ref = _git(["rev-parse", "refs/remotes/origin/klc-state"], proj).stdout.strip()

    # recreate klc-state with rewritten (non-ff) history → NEW, then force-push
    _git(["checkout", "klc-state"], build)
    (build / "tickets" / "o.txt").write_text("NEW", encoding="utf-8")
    _git(["add", "-A"], build)
    _git(["commit", "--amend", "-m", "new klc-state"], build)
    _git(["checkout", "main"], build)
    _git(["push", "--force", str(origin), "klc-state"], build)
    new_tip = _git(["ls-remote", str(origin), "klc-state"], proj).stdout.split()[0]
    assert new_tip != old_ref, "test setup: remote tip must have been rewritten"

    rc = _run_in(proj, ["init"])
    assert rc == 0, "init should materialize the recreated remote tip"
    assert (proj / ".klc" / "tickets" / "o.txt").read_text(encoding="utf-8") == "NEW", \
        "must materialize the recreated remote tip, not the stale tracking ref"
    head = _git(["rev-parse", "klc-state"], proj).stdout.strip()
    assert head == new_tip, "local klc-state must point at the new remote tip"


# --- r4-review2 #1: fetch the BRANCH klc-state, never a same-named tag --------


def test_state_init_fetches_branch_not_same_named_tag(tmp_path):
    """If the remote has BOTH a branch and a tag named klc-state, an unqualified
    fetch source resolves the TAG (DWIM prefers refs/tags/). init must fetch the
    verified BRANCH via a fully-qualified `refs/heads/klc-state` source."""
    build = tmp_path / "build"
    build.mkdir()
    _init_repo(build)

    # branch klc-state at commit A
    _git(["checkout", "--orphan", "klc-state"], build)
    _git(["rm", "-rf", "--cached", "."], build, check=False)
    (build / "a.txt").unlink()
    (build / "tickets").mkdir()
    (build / "tickets" / "o.txt").write_text("BRANCH_A", encoding="utf-8")
    _git(["add", "-A"], build)
    _git(["commit", "-m", "branch A"], build)
    _git(["checkout", "main"], build)

    # tag klc-state at a DIFFERENT, disjoint commit B
    _git(["checkout", "--orphan", "tagbase"], build)
    _git(["rm", "-rf", "--cached", "."], build, check=False)
    (build / "a.txt").unlink()
    (build / "tickets").mkdir()
    (build / "tickets" / "o.txt").write_text("TAG_B", encoding="utf-8")
    _git(["add", "-A"], build)
    _git(["commit", "-m", "tag B"], build)
    tag_sha = _git(["rev-parse", "HEAD"], build).stdout.strip()
    _git(["checkout", "main"], build)
    _git(["branch", "-D", "tagbase"], build)
    _git(["tag", "klc-state", tag_sha], build)

    origin = tmp_path / "origin.git"
    _git(["clone", "--bare", str(build), str(origin)], tmp_path)
    # sanity: origin carries both a branch and a tag named klc-state
    refs = _git(["for-each-ref"], origin).stdout
    assert "refs/heads/klc-state" in refs and "refs/tags/klc-state" in refs

    proj = tmp_path / "proj"
    _git(["clone", str(origin), str(proj)], tmp_path)
    _git(["config", "user.name", "t"], proj)
    _git(["config", "user.email", "t@t"], proj)

    rc = _run_in(proj, ["init"])
    assert rc == 0
    assert (proj / ".klc" / "tickets" / "o.txt").read_text(encoding="utf-8") == "BRANCH_A", \
        "must materialize the BRANCH klc-state, not the same-named tag"


# --- r4-review2 #2: a failed fetch in the present path restores the backup ----


def _inject_fetch_failure(state):
    """Make the `git fetch` in the present path exit non-zero."""
    real = state._git

    def fake(args, cwd, *, check=True):
        if args and args[0] == "fetch":
            return subprocess.CompletedProcess(
                ["git", "fetch"], 1, stdout="", stderr="injected fetch failure"
            )
        return real(args, cwd, check=check)

    state._git = fake


def test_state_init_fetch_failure_restores_backup(tmp_path):
    origin = _make_origin_with_state(tmp_path)  # origin klc-state with tickets/origin.txt

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["fetch", "origin"], root)  # status becomes "present"

    # local pre-existing ticket content that must survive a failed fetch
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("PRECIOUS", encoding="utf-8")

    rc = _run_in_patched(root, ["init"], _inject_fetch_failure)
    assert rc == 1, "a failed fetch in the present path must report failure"

    # backup restored in place, nothing stranded, no partial worktree
    assert (root / ".klc" / "tickets" / "local.txt").read_text(encoding="utf-8") == "PRECIOUS"
    assert not (root / ".klc.init-bak").exists(), "backup must not be left stranded"
    assert str((root / ".klc").resolve()) not in _worktree_paths(root)


# --- ws-fix #1: orphan bootstrap publishes klc-state so state_sync can drive it


def test_state_init_orphan_bootstrap_pushes_and_sets_upstream(tmp_path):
    """Bootstrapping state against a reachable remote must push klc-state and
    set its upstream, so state_sync (054) — which requires @{upstream} — can
    operate on a fresh project."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", str(origin)], tmp_path)

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)

    rc = _run_in(root, ["init"])
    assert rc == 0

    # klc-state now exists on origin
    assert _git(["ls-remote", str(origin), "klc-state"], root).stdout.strip(), \
        "klc-state must be pushed to origin"
    # and .klc's upstream resolves to origin/klc-state
    up = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], root / ".klc", check=False
    ).stdout.strip()
    assert up == "origin/klc-state", f"upstream not set to origin/klc-state: {up!r}"


def test_state_init_orphan_bootstrap_no_remote_ok(tmp_path):
    """No remote configured → pure local bootstrap is valid: exit 0, no upstream,
    no crash."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)  # no remote

    rc = _run_in(root, ["init"])
    assert rc == 0
    assert (root / ".klc").is_dir()
    up = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], root / ".klc", check=False
    )
    assert up.returncode != 0, "no remote → klc-state should have no upstream"


def _inject_push_failure(state):
    real = state._git

    def fake(args, cwd, *, check=True):
        if args and args[0] == "push":
            return subprocess.CompletedProcess(
                ["git", "push"], 1, stdout="", stderr="injected push failure"
            )
        return real(args, cwd, check=check)

    state._git = fake


def test_state_init_orphan_bootstrap_push_failure_warns_but_succeeds(tmp_path, capsys):
    """Remote configured but push fails (offline/auth) → warn and still exit 0;
    local init succeeded, don't strand the user."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", str(origin)], tmp_path)

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)

    rc = _run_in_patched(root, ["init"], _inject_push_failure)
    assert rc == 0, "local init must succeed even if the push fails"
    assert (root / ".klc").is_dir()
    err = capsys.readouterr().err
    assert "not pushed" in err and "push -u" in err, f"missing/incomplete warning: {err!r}"


# --- ws-fix #2: a sub-namespace fetch refspec must not break klc-state tracking


def test_state_init_subnamespace_refspec_tracks_state(tmp_path):
    """A custom fetch refspec that writes to refs/remotes/origin/* from only a
    SUB-namespace (refs/heads/release/*) must not fool the 'covered' check:
    klc-state is not actually fetched by it, so init must still bind tracking to
    refs/heads/klc-state and a later `git pull` in .klc must work."""
    origin = _make_origin_with_state(tmp_path)  # origin klc-state with tickets/origin.txt

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["config", "--unset-all", "remote.origin.fetch"], root, check=False)
    _git(["config", "--add", "remote.origin.fetch",
          "+refs/heads/release/*:refs/remotes/origin/*"], root)

    rc = _run_in(root, ["init"])
    assert rc == 0

    merge = _git(["config", "branch.klc-state.merge"], root / ".klc", check=False).stdout.strip()
    assert merge == "refs/heads/klc-state", f"merge ref bound wrong: {merge!r}"
    up = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], root / ".klc", check=False
    ).stdout.strip()
    assert up == "origin/klc-state", f"upstream wrong: {up!r}"
    # a real pull in the worktree must succeed
    pull = _git(["pull"], root / ".klc", check=False)
    assert pull.returncode == 0, f"git pull in .klc failed: {pull.stderr!r}"


# --- ws-fix2: orphan bootstrap must set a resolvable upstream on single-branch
# ---          clones too (converge with the present path's tail) -------------


def test_state_init_orphan_bootstrap_single_branch_clone_sets_upstream(tmp_path):
    """Bootstrapping state (orphan path) in a SINGLE-BRANCH clone must still
    leave a resolvable @{upstream}: push -u alone writes branch.*.merge but the
    single-branch fetch refspec never materializes refs/remotes/<remote>/
    klc-state, so state_sync (which hard-requires @{upstream}) would fail."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", str(origin)], tmp_path)
    # seed origin with a main branch so --single-branch --branch main works
    seed = tmp_path / "seed"
    seed.mkdir()
    _init_repo(seed)
    _git(["push", str(origin), "main"], seed)

    proj = tmp_path / "proj"
    _git(["clone", "--single-branch", "--branch", "main", str(origin), str(proj)], tmp_path)
    _git(["config", "user.name", "t"], proj)
    _git(["config", "user.email", "t@t"], proj)
    # sanity: this clone's fetch refspec covers only main
    assert _git(["config", "--get-all", "remote.origin.fetch"], proj).stdout.strip() == \
        "+refs/heads/main:refs/remotes/origin/main"

    rc = _run_in(proj, ["init"])
    assert rc == 0

    # klc-state pushed to origin
    assert _git(["ls-remote", str(origin), "klc-state"], proj).stdout.strip(), \
        "klc-state must be pushed to origin"
    # the remote-tracking ref is materialized AND @{upstream} resolves
    assert _git(
        ["rev-parse", "--verify", "--quiet", "refs/remotes/origin/klc-state"], proj, check=False
    ).returncode == 0, "refs/remotes/origin/klc-state must exist"
    up = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], proj / ".klc", check=False
    ).stdout.strip()
    assert up == "origin/klc-state", f"upstream must resolve on single-branch clone, got {up!r}"


# --- ws-fix3: orphan bootstrap must push a BRANCH even when a same-named tag --
# ---          exists (unqualified push source is ambiguous) ------------------


def test_state_init_orphan_bootstrap_with_same_named_tag_pushes_branch(tmp_path):
    """If a tag `klc-state` also exists, an unqualified `git push -u origin
    klc-state` is rejected ('src refspec ... matches more than one'), leaving no
    remote branch and no upstream even though the remote was reachable. The push
    must be branch-qualified so it publishes refs/heads/klc-state and @{upstream}
    resolves."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", str(origin)], tmp_path)

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    # a TAG named klc-state exists (no branch yet) → unqualified push is ambiguous
    _git(["tag", "klc-state", "HEAD"], root)

    rc = _run_in(root, ["init"])
    assert rc == 0

    # a real BRANCH refs/heads/klc-state was pushed to origin (not rejected)
    heads = _git(["ls-remote", "--heads", str(origin), "klc-state"], root).stdout.strip()
    assert heads, "orphan bootstrap must push a refs/heads/klc-state branch to origin"
    # and @{upstream} resolves so state_sync can operate
    up = _git(
        ["rev-parse", "--abbrev-ref", "klc-state@{upstream}"], root / ".klc", check=False
    ).stdout.strip()
    assert up == "origin/klc-state", f"upstream must resolve, got {up!r}"


# --- KLC-063: preserved tickets must be committed AND pushed ----------------


def _bare_origin(tmp_path: Path) -> Path:
    """A fresh bare 'origin' with NO klc-state branch (drives the orphan-create
    path, where init creates+pushes klc-state and must also push preserved
    tickets)."""
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], tmp_path)
    return bare


def test_state_init_commits_and_pushes_preserved_tickets(tmp_path):
    """AC-1 / AC-6a: `klc state init` on a repo with pre-existing `.klc/tickets`
    must COMMIT the preserved tickets on klc-state and PUSH them to origin, so a
    second clone tracking origin/klc-state receives them. Fails today because
    `_merge_back` copies but never commits."""
    bare = _bare_origin(tmp_path)

    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(bare)], root)

    # pre-existing preserved ticket in a plain .klc directory (orphan-create path)
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("LOCAL-TICKET", encoding="utf-8")

    assert _run_in(root, ["init"]) == 0

    # committed on the local klc-state branch
    show = _git(["show", "klc-state:tickets/local.txt"], root, check=False)
    assert show.returncode == 0 and show.stdout == "LOCAL-TICKET", \
        "preserved ticket must be COMMITTED on klc-state, not left uncommitted"
    # and pushed to origin/klc-state
    rshow = _git(["show", "origin/klc-state:tickets/local.txt"], root, check=False)
    assert rshow.returncode == 0 and rshow.stdout == "LOCAL-TICKET", \
        "preserved ticket must be PUSHED to origin/klc-state"

    # a SECOND clone tracking origin/klc-state receives it via state init
    clone = tmp_path / "clone"
    clone.mkdir()
    _init_repo(clone)
    _git(["remote", "add", "origin", str(bare)], clone)
    _git(["fetch", "origin"], clone)
    assert _run_in(clone, ["init"]) == 0
    assert (clone / ".klc" / "tickets" / "local.txt").read_text(encoding="utf-8") \
        == "LOCAL-TICKET", "a second clone must receive the preserved ticket"


def test_state_init_no_preserved_content_makes_no_empty_commit(tmp_path):
    """AC-2: with nothing to preserve, init must NOT create an empty commit — the
    orphan klc-state keeps its single root commit and output/exit code are
    unchanged."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    assert _run_in(root, ["init"]) == 0

    count = _git(["rev-list", "--count", "klc-state"], root).stdout.strip()
    assert count == "1", \
        f"no preserved content must not add a commit; got {count} commits on klc-state"


def _reject_pushes(bare: Path) -> None:
    """Install a pre-receive hook on the bare origin that rejects every push — a
    REAL mechanism (057 style) to force the preserved-tickets push to fail."""
    hooks = bare / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def _reject_commits(root: Path) -> None:
    """Install a pre-commit hook in the repo (shared by the `.klc` worktree) that
    rejects every commit — a REAL mechanism to force `_commit_preserved` to fail.
    Used on the track-origin path where `_add_worktree` makes NO commit, so only
    the preserved-tickets commit is affected."""
    hooks = root / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def test_state_init_excludes_derived_from_preserved_commit(tmp_path):
    """AC-1 / INV7: preserved DERIVED/local artifacts (.lock, _prompt.md,
    .index.json, scratch/, knowledge/tickets-index.jsonl) must be EXCLUDED from
    the klc-state commit and never pushed — only real ticket state is shared.
    Fails today: a bare `git add -A` (no derived-ignore applied at init) commits
    and pushes every derived file."""
    bare = _bare_origin(tmp_path)
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(bare)], root)

    klcd = root / ".klc"
    tk = klcd / "tickets" / "KLC-9001"
    (tk / "design").mkdir(parents=True)
    (tk / "scratch").mkdir(parents=True)
    (tk / "meta.json").write_text('{"ticket":"KLC-9001"}\n', encoding="utf-8")  # REAL
    (tk / ".lock").write_text("pid\n", encoding="utf-8")                        # derived
    (tk / ".index.json").write_text("{}\n", encoding="utf-8")                   # derived
    (tk / "design" / "_prompt.md").write_text("card\n", encoding="utf-8")       # derived
    (tk / "scratch" / "note.txt").write_text("local\n", encoding="utf-8")       # derived
    (klcd / "knowledge").mkdir()
    (klcd / "knowledge" / "tickets-index.jsonl").write_text(
        '{"ticket":"KLC-9001"}\n', encoding="utf-8")                            # derived

    assert _run_in(root, ["init"]) == 0

    committed = _git(["ls-tree", "-r", "--name-only", "klc-state"], root).stdout
    assert "tickets/KLC-9001/meta.json" in committed, \
        f"the real ticket must be committed; tree was:\n{committed}"
    for derived in ("tickets/KLC-9001/.lock", "tickets/KLC-9001/.index.json",
                    "tickets/KLC-9001/design/_prompt.md",
                    "tickets/KLC-9001/scratch/note.txt",
                    "knowledge/tickets-index.jsonl"):
        assert derived not in committed, \
            f"derived file leaked into klc-state: {derived}\ntree:\n{committed}"

    # a second clone must inherit the real ticket but NONE of the derived files
    clone = tmp_path / "clone"
    clone.mkdir()
    _init_repo(clone)
    _git(["remote", "add", "origin", str(bare)], clone)
    _git(["fetch", "origin"], clone)
    assert _run_in(clone, ["init"]) == 0
    assert (clone / ".klc" / "tickets" / "KLC-9001" / "meta.json").exists(), \
        "second clone must receive the real ticket"
    assert not (clone / ".klc" / "knowledge" / "tickets-index.jsonl").exists(), \
        "second clone must not inherit the shared derived index"
    assert not (clone / ".klc" / "tickets" / "KLC-9001" / ".lock").exists(), \
        "second clone must not inherit a shared .lock"


def test_state_init_preserved_commit_failure_preserves_tickets_no_crash(tmp_path):
    """AC-2 / data-loss: if the preserved-tickets COMMIT fails, init must return 1
    cleanly (no traceback) and the user's preserved tickets must SURVIVE. Fails
    today: `_merge_back` deletes the backup before the commit, so a commit failure
    tears down the merged worktree and crashes with FileNotFoundError, destroying
    the only copy."""
    origin = _make_origin_with_state(tmp_path)  # track-origin → no orphan-root commit
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["fetch", "origin"], root)

    (root / ".klc" / "tickets").mkdir(parents=True)
    (root / ".klc" / "tickets" / "local.txt").write_text("PRECIOUS", encoding="utf-8")

    _reject_commits(root)  # ONLY the _commit_preserved commit will fire+fail

    rc = _run_in(root, ["init"])  # must NOT raise
    assert rc == 1, "a preserved-commit failure must return 1 cleanly (no crash)"

    survivor = root / ".klc" / "tickets" / "local.txt"
    bak = root / ".klc.init-bak" / "tickets" / "local.txt"
    assert survivor.exists() or bak.exists(), \
        "the preserved ticket must survive a failed preserved-commit"
    content = (survivor if survivor.exists() else bak).read_text(encoding="utf-8")
    assert content == "PRECIOUS", "preserved ticket content must be intact"


def test_state_init_preserved_commit_pushfail_warns_exit0(tmp_path, capsys):
    """AC-2: when the preserved-tickets PUSH fails (offline / auth / permission),
    init must warn and still exit 0 — the tickets are committed locally and
    nothing is stranded. Uses a REAL pre-receive hook (057 style), not a git
    monkeypatch."""
    bare = _bare_origin(tmp_path)
    _reject_pushes(bare)  # the remote rejects every push, for real
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(bare)], root)

    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("LOCAL-TICKET", encoding="utf-8")

    rc = _run_in(root, ["init"])
    assert rc == 0, "a preserved-tickets push failure must not fail init"

    err = capsys.readouterr().err.lower()
    assert "not pushed" in err, f"expected a 'not pushed' warning, got: {err!r}"
    # committed locally even though the push failed → nothing stranded
    show = _git(["show", "klc-state:tickets/local.txt"], root, check=False)
    assert show.returncode == 0 and show.stdout == "LOCAL-TICKET", \
        "preserved ticket must be committed locally despite the push failure"
    # the worktree stays intact (not torn down)
    assert str((root / ".klc").resolve()) in _worktree_paths(root)


def _exclude_bytes(root: Path) -> bytes:
    p = root / ".git" / "info" / "exclude"
    return p.read_bytes() if p.exists() else b""


def test_state_init_does_not_mutate_repo_exclude(tmp_path):
    """P2-A: init must exclude preserved derived files from the klc-state commit
    WITHOUT touching the repo-wide `.git/info/exclude` (a COMMON, shared file —
    polluting it makes unrelated main-worktree files silently ignored). Fails on
    the ensure_derived_ignored-based fix (which appends to info/exclude)."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)

    klcd = root / ".klc"
    tk = klcd / "tickets" / "KLC-9100"
    (tk / "scratch").mkdir(parents=True)
    (tk / "meta.json").write_text('{"ticket":"KLC-9100"}\n', encoding="utf-8")  # REAL
    (tk / ".lock").write_text("pid\n", encoding="utf-8")                        # derived
    (tk / "scratch" / "note.txt").write_text("local\n", encoding="utf-8")       # derived
    (klcd / "knowledge").mkdir()
    (klcd / "knowledge" / "tickets-index.jsonl").write_text("{}\n", encoding="utf-8")

    before = _exclude_bytes(root)
    assert _run_in(root, ["init"]) == 0
    after = _exclude_bytes(root)

    assert after == before, \
        "klc state init must NOT mutate the repo-wide .git/info/exclude"
    # and the derived files are STILL excluded from the committed tree
    committed = _git(["ls-tree", "-r", "--name-only", "klc-state"], root).stdout
    assert "tickets/KLC-9100/meta.json" in committed
    for derived in ("tickets/KLC-9100/.lock", "tickets/KLC-9100/scratch/note.txt",
                    "knowledge/tickets-index.jsonl"):
        assert derived not in committed, f"derived file leaked: {derived}"


def _fail_backup_cleanup(state):
    """Make ONLY the post-success backup rmtree fail (as an unwritable/read-only
    backup would), honoring `ignore_errors` so the CURRENT code silently swallows
    it — proving the RED (no warning). Scoped to this loaded module instance via a
    shutil shim, so it never mutates the process-global shutil."""
    import shutil as _real

    class _ShutilShim:
        def __getattr__(self, name):
            return getattr(_real, name)

        def rmtree(self, path, *a, **k):
            if str(path).endswith(state._BACKUP_DIR):
                if k.get("ignore_errors"):
                    return  # mimic real ignore_errors: swallow → leftover remains
                raise OSError("simulated: backup is read-only")
            return _real.rmtree(path, *a, **k)

    state.shutil = _ShutilShim()


def test_state_init_backup_cleanup_failure_surfaces_warning(tmp_path, capsys):
    """P2-B: if the post-success backup cleanup fails, init must NOT silently claim
    success with a hidden leftover — it warns (leftover path visible) so the next
    init's backup-preflight break is not a surprise. Fails on the
    ignore_errors=True code (no warning emitted)."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    tdir = root / ".klc" / "tickets"
    tdir.mkdir(parents=True)
    (tdir / "local.txt").write_text("LOCAL-TICKET", encoding="utf-8")

    rc = _run_in_patched(root, ["init"], _fail_backup_cleanup)
    assert rc == 0, "a cleanup failure must not hard-fail an otherwise-successful init"
    err = capsys.readouterr().err.lower()
    assert ".klc.init-bak" in err and "backup" in err, \
        f"a leftover-backup warning must be surfaced (not silently ignored): {err!r}"


def test_state_init_converges_out_tracked_derived_on_upgrade(tmp_path):
    """FINDING-3 / INV7 upgrade case: when klc-state ALREADY TRACKS a derived file
    (legacy layout), init must converge it OUT (git rm --cached) so the preserved
    commit removes it from the shared branch and the worktree ends clean w.r.t.
    TRACKED files. Fails today: the exclude-only `git add` neither stages the
    local modification nor removes it → dirty tree + still-tracked derived file."""
    origin = _make_origin_with_state(tmp_path, files={
        "knowledge/tickets-index.jsonl": "OLD-INDEX\n",       # legacy TRACKED derived
        "tickets/KLC-ORIG/meta.json": '{"ticket":"KLC-ORIG"}\n',
    })
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    _git(["remote", "add", "origin", str(origin)], root)
    _git(["fetch", "origin"], root)

    # local .klc carries a NEWER copy of the tracked derived file + a real new ticket
    klcd = root / ".klc"
    (klcd / "knowledge").mkdir(parents=True)
    (klcd / "knowledge" / "tickets-index.jsonl").write_text("NEW-LOCAL-INDEX\n", encoding="utf-8")
    (klcd / "tickets" / "KLC-NEW").mkdir(parents=True)
    (klcd / "tickets" / "KLC-NEW" / "meta.json").write_text('{"ticket":"KLC-NEW"}\n', encoding="utf-8")

    assert _run_in(root, ["init"]) == 0

    # (a) worktree clean w.r.t. TRACKED files (no staged/modified tracked derived)
    status = _git(["status", "--porcelain", "--untracked-files=no"], klcd).stdout.strip()
    assert status == "", f"worktree must be clean w.r.t. tracked files, got: {status!r}"

    # (b) the legacy tracked derived file is REMOVED from the klc-state tree
    committed = _git(["ls-tree", "-r", "--name-only", "klc-state"], root).stdout
    assert "knowledge/tickets-index.jsonl" not in committed, \
        f"legacy tracked derived file must be converged OUT of klc-state; tree:\n{committed}"

    # (c) real ticket content intact and committed (both the origin one and the new one)
    assert "tickets/KLC-NEW/meta.json" in committed, "the new preserved ticket must be committed"
    assert "tickets/KLC-ORIG/meta.json" in committed, "the pre-existing ticket must remain"
    # the derived file remains on disk (untracked) for the runtime to hide later
    assert (klcd / "knowledge" / "tickets-index.jsonl").exists(), \
        "the derived file must stay on disk (only untracked), not be deleted"


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
