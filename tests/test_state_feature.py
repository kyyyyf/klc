"""KLC-057 step-1: state_feature.enabled() — authoritative multi-user switch.

`enabled()` is True iff `.klc/` is a git worktree bound to the `klc-state`
branch AND that branch has a configured upstream. Both conditions are required:
state_sync.pull_rebase / commit_and_push_cas hard-require `@{upstream}`, so a
no-remote single-user `klc-state` orphan (no upstream) must read as OFF and the
verbs must behave exactly as today.

All tests run against local git repos (file paths, no network).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import state_feature  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers: local git repos with a klc-state worktree (zero network)
# ---------------------------------------------------------------------------

def _git(args, cwd, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "t"], root)
    (root / "a.txt").write_text("hi", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "init"], root)


def _make_origin_with_state(tmp: Path) -> Path:
    build = tmp / "build"
    _init_repo(build)
    _git(["checkout", "--orphan", "klc-state"], build)
    _git(["rm", "-rf", "--cached", "."], build, check=False)
    (build / "a.txt").unlink()
    (build / "tickets").mkdir()
    (build / "tickets" / "seed.txt").write_text("seed", encoding="utf-8")
    _git(["add", "-A"], build)
    _git(["commit", "-m", "klc-state root"], build)
    _git(["checkout", "main"], build)
    bare = tmp / "origin.git"
    _git(["clone", "--bare", str(build), str(bare)], tmp)
    return bare


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_enabled_false_when_klc_is_plain_dir(tmp_path, monkeypatch):
    """A plain `.klc/` directory (HEAD is not the klc-state branch) → False."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / ".klc").mkdir()
    assert state_feature.enabled() is False


def test_enabled_true_when_klc_state_worktree_with_upstream(tmp_path, monkeypatch):
    """`.klc/` on the klc-state branch WITH a configured upstream → True."""
    origin = _make_origin_with_state(tmp_path)
    proj = tmp_path / "proj"
    _git(["clone", str(origin), str(proj)], tmp_path)
    _git(["config", "user.email", "t@t"], proj)
    _git(["config", "user.name", "t"], proj)
    _git(["worktree", "add", "--track", "-b", "klc-state",
          str(proj / ".klc"), "origin/klc-state"], proj)

    monkeypatch.setenv("PROJECT_ROOT", str(proj))
    assert state_feature.enabled() is True


def test_enabled_false_when_klc_state_worktree_without_upstream(tmp_path, monkeypatch):
    """`.klc/` on the klc-state branch but with NO upstream → False (fail-safe).

    state_sync's verbs hard-require @{upstream}; a no-remote klc-state orphan
    would crash them, so the feature must read OFF (behave as single-user).
    """
    root = tmp_path / "proj"
    _init_repo(root)
    _git(["branch", "klc-state"], root)  # local branch, no remote/upstream
    _git(["worktree", "add", str(root / ".klc"), "klc-state"], root)

    monkeypatch.setenv("PROJECT_ROOT", str(root))
    # sanity: HEAD really is klc-state but @{upstream} does not resolve
    up = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name",
               "klc-state@{upstream}"], root / ".klc", check=False)
    assert up.returncode != 0

    assert state_feature.enabled() is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
