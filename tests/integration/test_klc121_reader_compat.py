#!/usr/bin/env python3
"""KLC-121 step-3 — AC-2: every existing reader of `structural.json`
tolerates both the pre-KLC-121 shape (no `files` map, no `schema_version`/
`fingerprint_algo`/`profile_identity` scalars — the keys genuinely ABSENT,
not merely empty) and the new one.

[!DECISION D-302] (build, this ticket): AC-2's own text names four things —
`file_universe.resolve`, `index_coverage.universe_for`,
`modules_build.module_file_universe`, and "each planning-view builder" —
and test-plan.md's Notes column expands the last into five names (test_map,
symbol_usage, module_edges, import-graph, file_roles). `module_edges.py`
never reads `structural.json` at all (verified: no reference to the string
"structural" anywhere in its source) — F-013 attributes its one
profile-resolver spawn to `test_conventions`, not to any structural-shape
dependency, and its own argparse has no `--in-structural`/`--structural`
flag. Testing it here would fabricate a dependency it does not have. The
seven readers below (three importable functions + test_map/symbol_usage/
import-graph/file_roles) are the real, complete set.

These two tests are REGRESSION GUARDS, not red-before-green tests in the
traditional sense: every one of the seven readers is UNCHANGED by this
ticket (only `file_scanner.py` and the new `index_fingerprint.py` module
are touched by step-3), so their tolerance of the old shape holds both
before and after this step lands — exactly analogous to step-1's
`test_builder_runs_standalone_without_a_handed_profile`, which also needed
no source change to pass. The "old" shape below is derived by deleting the
four new keys from a live run (making them genuinely ABSENT, not empty) —
build-log.md's step-3 entry records that this was cross-checked against a
literal `git show HEAD:` (pre-step-3) `file_scanner.py` run during RED
verification, so the comparison is not circular.
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

import file_universe  # noqa: E402
import index_coverage  # noqa: E402
import modules_build  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args],
                    capture_output=True, text=True, timeout=15)


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "pkg" / "test_a.py").write_text(
        "from pkg.a import f\n\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    env = dict(os.environ, PROJECT_ROOT=str(root))
    r = subprocess.run(
        [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--scan-only"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return root


def _old_shape(structural: dict) -> dict:
    """The pre-KLC-121 shape: the four new keys genuinely ABSENT (popped),
    not merely present-and-empty (test-plan.md's explicit fail-closed
    clause: "not an empty map — the KEY itself absent")."""
    d = dict(structural)
    for key in ("files", "schema_version", "fingerprint_algo", "profile_identity"):
        d.pop(key, None)
    return d


def _read_file_universe(root, structural):
    return file_universe.resolve(root, structural=structural)


def _read_index_coverage(root, structural):
    return index_coverage.universe_for(None, structural)


def _read_modules_build(root, structural):
    return modules_build.module_file_universe(root, structural=structural)


PY_READERS = {
    "file_universe.resolve": _read_file_universe,
    "index_coverage.universe_for": _read_index_coverage,
    "modules_build.module_file_universe": _read_modules_build,
}

CLI_READERS = {
    "test_map": dict(script="test_map.py", flag="--in-structural"),
    "symbol_usage": dict(script="symbol_usage.py", flag="--in-structural"),
    "import-graph": dict(script="import-graph.py", flag="--structural"),
    "file_roles": dict(script="file_roles.py", flag="--in-structural"),
}

READER_NAMES = tuple(PY_READERS) + tuple(CLI_READERS)


def _run_cli_reader(name: str, root: Path, structural_path: Path, out_path: Path):
    spec = CLI_READERS[name]
    script = SKILLS / spec["script"]
    env = dict(os.environ, PROJECT_ROOT=str(root))
    argv = [sys.executable, str(script), spec["flag"], str(structural_path)]
    if name != "import-graph":
        argv += ["--out", str(out_path)]
    r = subprocess.run(argv, cwd=str(root), env=env,
                        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"{name} failed: {r.stderr}"
    if name == "import-graph":
        return json.loads(r.stdout)
    return json.loads(out_path.read_text(encoding="utf-8"))


def _strip_volatile(d):
    if not isinstance(d, dict):
        return d
    d = dict(d)
    d.pop("generated_at", None)
    return d


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return _make_repo(tmp_path_factory.mktemp("klc121-reader-compat"))


@pytest.fixture(scope="module")
def structural_new(repo):
    return json.loads((repo / ".klc" / "index" / "structural.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def structural_old(structural_new):
    return _old_shape(structural_new)


@pytest.mark.parametrize("reader", READER_NAMES)
@pytest.mark.parametrize("shape", ("old", "new"))
def test_readers_tolerate_old_and_new_structural_shape(
        reader, shape, repo, structural_old, structural_new, tmp_path):
    """AC-2: file_universe.resolve, index_coverage.universe_for,
    modules_build.module_file_universe and each real structural.json-reading
    planning-view builder (test_map, symbol_usage, import-graph, file_roles
    — module_edges excluded, D-302) are each handed one artifact of each
    shape, and neither raises."""
    structural = structural_old if shape == "old" else structural_new
    if reader in PY_READERS:
        result = PY_READERS[reader](repo, structural)
        assert result is not None
    else:
        structural_path = tmp_path / f"{reader}-{shape}-structural.json"
        structural_path.write_text(json.dumps(structural), encoding="utf-8")
        out_path = tmp_path / f"{reader}-{shape}-out.json"
        result = _run_cli_reader(reader, repo, structural_path, out_path)
        assert result is not None


@pytest.mark.parametrize("reader", READER_NAMES)
def test_reader_given_old_shape_matches_todays_baseline_output_no_crash(
        reader, repo, structural_old, structural_new, tmp_path):
    """AC-2: NEGATIVE/fail-closed twin: each named reader handed the OLD
    structural.json shape (the four keys genuinely absent) does not raise,
    and its output is byte-for-byte equal (apart from `generated_at`) to
    the same reader handed the NEW shape — proving the new keys make no
    observable difference to any of these seven readers."""
    if reader in PY_READERS:
        old_result = PY_READERS[reader](repo, structural_old)
        new_result = PY_READERS[reader](repo, structural_new)
    else:
        old_path = tmp_path / f"{reader}-old-structural.json"
        old_path.write_text(json.dumps(structural_old), encoding="utf-8")
        old_out = tmp_path / f"{reader}-old-out.json"
        old_result = _strip_volatile(_run_cli_reader(reader, repo, old_path, old_out))

        new_path = tmp_path / f"{reader}-new-structural.json"
        new_path.write_text(json.dumps(structural_new), encoding="utf-8")
        new_out = tmp_path / f"{reader}-new-out.json"
        new_result = _strip_volatile(_run_cli_reader(reader, repo, new_path, new_out))

    assert old_result == new_result


if __name__ == "__main__":
    import unittest
    unittest.main()
