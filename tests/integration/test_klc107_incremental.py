#!/usr/bin/env python3
"""tests/integration/test_klc107_incremental.py — the tests KLC-107's design
reserved by name under `[!DECISION D-001]` (its own test-plan.md AC-20/23/24
rows), shipped here by KLC-121:

  - test_profile_resolved_exactly_once_per_run           (AC-3, KLC-107 AC-23)
  - test_structural_json_carries_stable_per_file_fingerprint (AC-1, KLC-107 AC-20)  [step-3]
  - test_incremental_falls_back_to_full_rebuild_and_says_so  (AC-6, KLC-107 AC-24)  [step-4]

KLC-107's own fifth reserved name, `test_incremental_output_matches_full_rebuild`
(AC-22, the byte-identical incremental-vs-full-rebuild property test), is NOT
shipped here — it travels to KLC-125 along with the merge it tests
(spec.md "What moved to KLC-125"; `tests/integration/test_klc107_meta.py`
asserts its continued absence, re-pointed from KLC-121 to KLC-125 in step-6).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import _klc121_spawn_probe as _probe  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args],
                    capture_output=True, text=True, timeout=15)


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _advance_head(root: Path) -> None:
    (root / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "advance")


@pytest.mark.parametrize("entry_point", ("init", "update"))
def test_profile_resolved_exactly_once_per_run(entry_point, tmp_path):
    """AC-3: one complete `klc init --scan-only` or `klc update` run spawns
    the profile resolver exactly once, measured against the F-013 baseline
    of 13 spawns for 7 distinct fields from 8 builders (KLC-121 build-log.md
    D-301 recomputes F-013's own "seven" to the complete set its own
    per-parent-process breakdown names). Carries KLC-107 AC-23; this exact
    test name and file are reserved by KLC-107 test-plan.md:33 (F-011) and
    closes AC-10's bookkeeping jointly with the AC-1/AC-6 rows above."""
    mirror = _probe.build_core_mirror(tmp_path / "mirror")
    repo = _make_repo(tmp_path)
    env = dict(os.environ, PROJECT_ROOT=str(repo))

    if entry_point == "update":
        # Prime a baseline first (its own spawn count is irrelevant — a
        # throwaway log — this run is not the one under test), then move
        # HEAD so `update.py` has something to do.
        prime_log = tmp_path / "prime.spawns"
        r = subprocess.run(
            [sys.executable, str(mirror / "scripts" / "init.py"), "--scan-only"],
            cwd=str(repo), env=_probe.spawn_env(env, prime_log),
            capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, r.stderr
        _advance_head(repo)
        argv = [sys.executable, str(mirror / "scripts" / "update.py")]
    else:
        argv = [sys.executable, str(mirror / "scripts" / "init.py"), "--scan-only"]

    log = tmp_path / f"{entry_point}.spawns"
    r = subprocess.run(argv, cwd=str(repo), env=_probe.spawn_env(env, log),
                        capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr

    assert _probe.count_spawns(log) == 1, (
        f"{entry_point}: expected exactly 1 profile-resolve.py spawn for the "
        f"whole run, saw {_probe.count_spawns(log)}\nstdout:\n{r.stdout}\n"
        f"stderr:\n{r.stderr}")


def test_structural_json_carries_stable_per_file_fingerprint(tmp_path):
    """AC-1: `structural.json` publishes a per-file map keyed by every
    member of `files_rel`, each entry carrying a SHA-256 content digest
    and the file byte size, together with the scalars `schema_version`
    and `fingerprint_algo`. Two consecutive runs over an unmodified tree
    produce byte-identical maps; the map holds exactly one entry per
    universe member, and its length equals `total_files`. Carries KLC-107
    AC-20; this exact test name and file are reserved by KLC-107
    test-plan.md:33 (F-011) and closes AC-10's bookkeeping."""
    repo = tmp_path / "proj"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    env = dict(os.environ, PROJECT_ROOT=str(repo))
    script = FRAMEWORK_ROOT / "core" / "skills" / "file_scanner.py"

    r1 = subprocess.run([sys.executable, str(script), str(repo)],
                         env=env, capture_output=True, text=True, timeout=60)
    assert r1.returncode == 0, r1.stderr
    r2 = subprocess.run([sys.executable, str(script), str(repo)],
                         env=env, capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0, r2.stderr

    d1 = json.loads(r1.stdout)
    d2 = json.loads(r2.stdout)

    assert d1["schema_version"] == 1
    assert d1["fingerprint_algo"] == "sha256"
    assert isinstance(d1["files"], dict)
    assert len(d1["files"]) == d1["total_files"]
    assert set(d1["files"]) == set(d1["files_rel"])
    for rel in d1["files_rel"]:
        assert set(d1["files"][rel]) == {"sha256", "size"}

    assert d1["files"] == d2["files"]


def _set_key(path: Path, key: str, value) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")


_TRIGGER_CONDITIONS = (
    ("previous artifact absent",
     lambda p: p.unlink()),
    ("previous artifact unparseable",
     lambda p: p.write_text("{not valid json", encoding="utf-8")),
    ("schema_version mismatch",
     lambda p: _set_key(p, "schema_version", 999)),
    ("fingerprint_algo mismatch",
     lambda p: _set_key(p, "fingerprint_algo", "sha1")),
    ("files_rel_source mismatch",
     lambda p: _set_key(p, "files_rel_source", "walk")),
    ("profile identity mismatch",
     lambda p: _set_key(p, "profile_identity",
                         {"name": "other", "fields_sha256": "0" * 64})),
)


@pytest.mark.parametrize("condition, mutate", _TRIGGER_CONDITIONS,
                         ids=[c for c, _ in _TRIGGER_CONDITIONS])
def test_incremental_falls_back_to_full_rebuild_and_says_so(condition, mutate, tmp_path):
    """AC-6: an index refresh run logs exactly one line naming why it
    rebuilt everything. Each of the six trigger conditions is exercised as
    its own case against a real `klc update` run and asserted to print the
    form `full rebuild (reason: <condition>)`. Carries KLC-107 AC-24;
    reserved name/file per F-011; closes AC-10 jointly with the AC-1/AC-3
    rows above."""
    repo = tmp_path / "proj"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    env = dict(os.environ, PROJECT_ROOT=str(repo))
    r = subprocess.run(
        [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--scan-only"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr

    structural_path = repo / ".klc" / "index" / "structural.json"
    mutate(structural_path)

    (repo / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance")

    r = subprocess.run(
        [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "update.py")],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert f"full rebuild (reason: {condition})" in r.stdout, r.stdout


if __name__ == "__main__":
    import unittest
    unittest.main()
