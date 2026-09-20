#!/usr/bin/env python3
"""KLC-121 step-1/step-2 — every builder reads the profile through the one
shared accessor (`profile_cache.field()`), which resolves for itself only
when no run handed a payload down (AC-3, AC-4, C-007).

F-013's own fact text says "seven distinct builders" but its own breakdown
by parent process names EIGHT: file_scanner, deterministic_inventory,
dep_graph, test_map, symbol_usage, module_edges, import-graph, file_roles
(the last five all resolving `test_conventions` through
`test_conventions.active_table()`). test-plan.md's AC-4 row lists all eight
by name too. [!DECISION D-301] (build, this ticket): the discrepancy is an
off-by-one in spec.md F-013's own prose against its own enumerated list —
spec.md is sealed and not edited here — and this suite parametrizes over
the complete, actually-correct set of eight so that AC-3's "spawns exactly
once" claim is proven true for every consumer that exists, not merely
seven of the eight that do. `Expected:` counts in impl-plan.md step-1/
step-2 are recomputed accordingly and the recomputation is recorded in
build-log.md (impl-plan.md's own "How to read Expected" invites exactly
this when a builder parametrizes differently than the plan guessed).
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
import profile_cache  # noqa: E402

import _klc121_spawn_probe as _probe  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args],
                    capture_output=True, text=True, timeout=15)


def _make_repo(tmp_path: Path) -> Path:
    """A tiny real git repo with one production file and one colocated
    test, then a real `init.py --scan-only` (against the LIVE repo's own
    core/, not a mirror) so `.klc/index/*` is fully populated for the
    planning-view builders (test_map/file_roles/module_edges/symbol_usage)
    that read modules.json/inventory.json/depgraph.json as inputs."""
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


def _strip_volatile(d: dict) -> dict:
    d = dict(d)
    d.pop("generated_at", None)
    return d


# name -> (argv builder(root, out) -> list[str-or-Path], reads stdout instead of `out`)
BUILDER_SPECS: dict[str, dict] = {
    "file_scanner": dict(
        argv=lambda root, out: [str(SKILLS / "file_scanner.py"), str(root)],
        stdout=True,
    ),
    "dep_graph": dict(
        argv=lambda root, out: [str(SKILLS / "dep_graph.py"), str(root)],
        stdout=True,
    ),
    "deterministic_inventory": dict(
        argv=lambda root, out: [str(SKILLS / "deterministic_inventory.py"),
                                 "--root", str(root), "--out", str(out)],
        stdout=False,
    ),
    "test_map": dict(
        argv=lambda root, out: [str(SKILLS / "test_map.py"),
                                 "--root", str(root), "--out", str(out)],
        stdout=False,
    ),
    "symbol_usage": dict(
        argv=lambda root, out: [str(SKILLS / "symbol_usage.py"), "--out", str(out)],
        stdout=False,
    ),
    "module_edges": dict(
        argv=lambda root, out: [str(SKILLS / "module_edges.py"), "--edges-only",
                                 "--out-edges", str(out)],
        stdout=False,
    ),
    "import-graph": dict(
        argv=lambda root, out: [str(SKILLS / "import-graph.py")],
        stdout=True,
    ),
    "file_roles": dict(
        argv=lambda root, out: [str(SKILLS / "file_roles.py"),
                                 "--root", str(root), "--out", str(out)],
        stdout=False,
    ),
}
BUILDER_NAMES = tuple(BUILDER_SPECS)


def _run_builder(name: str, mirror_root: Path, project_root: Path, out: Path,
                  *, payload: dict | None, log: Path) -> dict:
    """Invoke *name* from the MIRROR (so its self-located FRAMEWORK_ROOT is
    the mirror, and its resolver body therefore reaches the counting stub
    at ``mirror/core/skills/profile-resolve.py``). *log* is ALWAYS wired —
    even when the caller does not care about the count — because the stub
    itself requires `KLC121_SPAWN_LOG`/`KLC121_REAL_RESOLVER` to run at
    all; omitting them would crash the stub, not merely skip counting."""
    spec = BUILDER_SPECS[name]
    script = mirror_root / "core" / "skills" / Path(spec["argv"](project_root, out)[0]).name
    argv = [sys.executable, str(script), *spec["argv"](project_root, out)[1:]]
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(project_root)
    if payload is not None:
        env[profile_cache.ENV_PAYLOAD] = json.dumps(payload, ensure_ascii=False)
    else:
        env.pop(profile_cache.ENV_PAYLOAD, None)
    env = _probe.spawn_env(env, log)
    r = subprocess.run(argv, cwd=str(project_root), env=env,
                        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"{name} failed: {r.stderr}"
    if spec["stdout"]:
        return json.loads(r.stdout)
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return _make_repo(tmp_path_factory.mktemp("klc121-profile-once"))


@pytest.fixture(scope="module")
def mirror(tmp_path_factory):
    return _probe.build_core_mirror(tmp_path_factory.mktemp("klc121-core-mirror"))


@pytest.fixture(scope="module")
def payload(repo):
    prev = os.environ.get("PROJECT_ROOT")
    os.environ["PROJECT_ROOT"] = str(repo)
    try:
        return profile_cache.resolve_profile_once()
    finally:
        if prev is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = prev


@pytest.mark.parametrize("builder", BUILDER_NAMES)
def test_builder_accepts_handed_down_profile_and_matches_standalone_byte_for_byte(
        builder, repo, mirror, payload, tmp_path):
    """AC-4: a builder handed a run-scoped profile payload spawns
    profile-resolve.py ZERO times (it reads the payload instead) and still
    writes the artifact a standalone, no-payload run of the same builder
    against the same repo writes, byte for byte apart from `generated_at`.
    Genuinely red before profile_cache.field() exists: today every builder
    always spawns regardless of KLC_PROFILE_PAYLOAD, so the zero-spawn
    assertion fails."""
    handed_log = tmp_path / "handed.spawns"
    handed_out = tmp_path / "handed.out.json"
    handed = _run_builder(builder, mirror, repo, handed_out,
                           payload=payload, log=handed_log)
    assert _probe.count_spawns(handed_log) == 0, (
        f"{builder} spawned profile-resolve.py {_probe.count_spawns(handed_log)} "
        f"time(s) despite a handed-down payload being present")

    standalone_out = tmp_path / "standalone.out.json"
    standalone_log = tmp_path / "standalone.spawns"
    standalone = _run_builder(builder, mirror, repo, standalone_out,
                               payload=None, log=standalone_log)

    assert _strip_volatile(handed) == _strip_volatile(standalone)


@pytest.mark.parametrize("builder", BUILDER_NAMES)
def test_builder_runs_standalone_without_a_handed_profile(builder, repo, mirror, tmp_path):
    """AC-4/C-007: with zero run-scoped environment/file state present, a
    builder still resolves its own field(s) via profile-resolve.py and
    completes — the handoff is an optimisation the run performs, never a
    precondition a builder may assume."""
    log = tmp_path / "standalone.spawns"
    out = tmp_path / "standalone.out.json"
    result = _run_builder(builder, mirror, repo, out, payload=None, log=log)
    assert result
    assert _probe.count_spawns(log) >= 1, (
        f"{builder} completed with zero profile-resolve.py spawns and no "
        f"handed-down payload — it must have resolved its own field(s)")


_PATCHED_BODY = '''def _resolve_profile_field(field: str) -> str:
    """Read the profile field this run already resolved, or resolve it for
    ourselves when no run handed one down (KLC-121 D-101/D-102). Signature
    and name unchanged, so `file_universe.py:80` and `modules_build.py:130`
    are covered by this repoint without an edit of their own."""
    return profile_cache.field(field)'''

_REVERTED_BODY = '''def _resolve_profile_field(field: str) -> str:
    """[KLC-121 test fixture, tests/integration/test_klc121_profile_once.py]
    deliberately reverted to a direct spawn, ignoring any handed-down
    payload — proves the AC-3 counter actually detects a regression."""
    script = FRAMEWORK_ROOT / "core" / "skills" / "profile-resolve.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--field", field],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip()'''


def test_spawn_counter_fixture_fails_when_a_second_spawn_is_reintroduced(tmp_path):
    """AC-3 negative twin: a deliberately-broken fixture build — one
    consumer (file_scanner) patched back to call profile-resolve.py
    directly instead of reading the handed-down payload — must make the
    AC-3 whole-run spawn-count assertion FAIL, proving the counter is
    sensitive to a regression and not a vacuous pass at 1 forever."""
    mirror = _probe.build_core_mirror(tmp_path / "mirror")
    fs_path = mirror / "core" / "skills" / "file_scanner.py"
    before_text = fs_path.read_text(encoding="utf-8")
    assert _PATCHED_BODY in before_text, (
        "file_scanner._resolve_profile_field's body shape changed — update "
        "this fixture's literal text to match")
    fs_path.write_text(before_text.replace(_PATCHED_BODY, _REVERTED_BODY),
                        encoding="utf-8")

    repo = _make_repo(tmp_path)
    log = tmp_path / "broken.spawns"
    env = _probe.spawn_env(dict(os.environ, PROJECT_ROOT=str(repo)), log)
    r = subprocess.run(
        [sys.executable, str(mirror / "scripts" / "init.py"), "--scan-only"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr

    assert _probe.count_spawns(log) != 1, (
        "the counting harness must be sensitive to a reintroduced spawn, "
        "not trivially read 1 forever")


if __name__ == "__main__":
    import unittest
    unittest.main()
