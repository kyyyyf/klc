"""KLC-105 step-6 — edge cases from test-plan.md's Edge cases section.

- Symlinked directories inside the tracked tree must not be dereferenced into the
  universe.
- Paths with spaces and Unicode characters round-trip unchanged.
- A tracked-but-excluded build/ artifact is dropped from files_rel even though
  `git ls-files` returns it.
- Windows path separators are normalised to POSIX in every artifact.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[2]
_skills = _repo_root / "core" / "skills"
sys.path.insert(0, str(_skills))
import file_scanner  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")


def test_symlinked_dir_does_not_expand_universe(tmp_path):
    """A symlink to a vendored/build tree inside the tracked tree must not be
    dereferenced and pull the target's contents into the universe."""
    root = tmp_path / "symlink_proj"
    _init_repo(root)
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    vendored = tmp_path / "vendored_elsewhere"
    vendored.mkdir()
    (vendored / "huge.py").write_text("y = 2\n", encoding="utf-8")

    try:
        (root / "vendor_link").symlink_to(vendored, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported in this environment")

    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed with a symlink")

    structural = file_scanner.scan(root)
    files_rel = structural["files_rel"]
    assert "pkg/mod.py" in files_rel
    assert not any("huge.py" in f for f in files_rel), (
        "a symlinked directory's target content leaked into the universe")


def test_paths_with_spaces_and_unicode_round_trip(tmp_path):
    """A path with spaces and Unicode characters must round-trip unchanged."""
    root = tmp_path / "unicode_proj"
    _init_repo(root)
    weird_dir = root / "src" / "café module"
    weird_dir.mkdir(parents=True)
    (weird_dir / "app.py").write_text("z = 3\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed with a unicode path")

    structural = file_scanner.scan(root)
    assert "src/café module/app.py" in structural["files_rel"]


def test_tracked_but_excluded_build_artifact_is_dropped(tmp_path):
    """A tracked-but-excluded build/ artifact (committed by mistake, matched by the
    baseline excludes regex) must be absent from files_rel even though
    `git ls-files` returns it."""
    root = tmp_path / "tracked_excluded_proj"
    _init_repo(root)
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "artifact.py").write_text("generated = True\n", encoding="utf-8")
    _git(root, "add", "-A", "-f")  # -f: force-add build/ despite any local ignore
    _git(root, "commit", "-q", "-m", "seed with a mistakenly-tracked build artifact")

    tracked = _git(root, "ls-files").splitlines()
    assert "build/artifact.py" in tracked, "test setup bug: build/ wasn't tracked"

    structural = file_scanner.scan(root)
    assert "build/artifact.py" not in structural["files_rel"], (
        "a tracked-but-baseline-excluded path leaked into files_rel")
    assert "pkg/mod.py" in structural["files_rel"]


def test_windows_separators_normalised_to_posix(monkeypatch):
    """Every artifact emits POSIX-style '/'-separated relative paths, even when a
    path was constructed with Windows-style separators.

    A fixture built with real `Path` objects on a POSIX runner can never actually
    contain a backslash (os.sep is '/' here, so `.replace(os.sep, "/")` is always a
    no-op on this platform regardless of whether the normalisation is present or
    correct) — that made the previous version of this test vacuously true on the
    only platform this suite runs on. Feed a pre-built backslash path STRING
    straight through the extracted `_to_posix` helper instead, with `os.sep`
    monkeypatched to '\\\\' so this genuinely exercises (and can fail) the
    normalisation logic on any runner."""
    monkeypatch.setattr(file_scanner.os, "sep", "\\")
    assert file_scanner._to_posix("pkg\\sub\\mod.py") == "pkg/sub/mod.py"
    assert file_scanner._to_posix("already/posix.py") == "already/posix.py"
