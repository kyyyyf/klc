"""KLC-106 step-9 — two falsifying fixtures and one healthy fixture, end to
end (AC-16, AC-17).

Real trees, real subprocess pipeline: `scripts/init.py --scan-only` (file
scanner -> dep_graph -> modules_build -> the planning views), then
`planning-retriever.py` for a real trace. No mocks.

The degraded-TypeScript and degraded-Python fixtures both use the SAME
mechanism a `baseUrl`-rooted TypeScript project exhibits in the wild: the
generic scanner's language-specific `source_roots` (the `generic` profile's
`conventional-dirs` discovery) cover only ONE real file (everything under
`src/`), while the language's total file count (the coverage denominator)
counts every file in the tree, including the ones under `legacy/` — this
repository's fixture stand-in for the FACT's "excluded working-copy
duplicates" / `baseUrl`-rooted-imports scenario. No `madge` needed (A-101):
no `package.json` ships in the TS fixture. Every fixture pins the `generic`
profile explicitly via a project `settings.yml`, regardless of whatever
this repo's own `config/profile.yml` currently says, so each fixture's
discovery mode stays independent of the framework's own ambient default.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _FW_ROOT / "tests" / "fixtures"
_SKILLS = _FW_ROOT / "core" / "skills"
_INIT = _FW_ROOT / "scripts" / "init.py"
_RETRIEVER = _SKILLS / "planning-retriever.py"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=30,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )


def _commit(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    r = _git(root, "commit", "-q", "-m", "seed fixture")
    assert r.returncode == 0, r.stderr


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    src = _FIXTURES / name
    dst = tmp_path / name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    # Pin the `generic` profile explicitly, regardless of whatever this
    # repo's own config/profile.yml currently says, so each fixture's
    # discovery mode (conventional-dirs) stays independent of the
    # framework's own ambient default.
    cfg = dst / ".klc" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.yml").write_text("profile: generic\n", encoding="utf-8")
    _commit(dst)
    return dst


def _run_pipeline(root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(root)
    return subprocess.run(
        [sys.executable, str(_INIT), "--scan-only"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=180,
    )


def _run_retriever(root: Path, query: str) -> dict:
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(root)
    r = subprocess.run(
        [sys.executable, str(_RETRIEVER), "--ticket", "KLC-999",
         "--query", query, "--out", "-"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _read(root: Path, name: str) -> dict:
    return json.loads((root / ".klc" / "index" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture,language", [
    ("klc106-degraded-ts", "typescript"),
    ("klc106-degraded-py", "python"),
])
def test_degraded_ts_and_py_fixtures_produce_degraded_flags_end_to_end(
        fixture, language, tmp_path):
    root = _copy_fixture(fixture, tmp_path)
    proc = _run_pipeline(root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    depgraph = _read(root, "depgraph.json")
    entry = depgraph["import_graphs"][language]
    assert entry["degraded"] is True, entry
    assert len(entry["nodes"]) == 1, entry["nodes"]

    trace = _run_retriever(root, query="helper module logic")
    assert trace["degraded_inputs"], trace
    assert trace["confidence"] == "low"
    assert all(m["confidence"] != "high" for m in trace["primary_modules"])


def test_healthy_fixture_produces_no_degraded_flags_and_unchanged_confidence(tmp_path):
    root = _copy_fixture("tiny-py", tmp_path)
    # D-212 (review round 1, HIGH finding #1) follow-up discovery: the
    # `generic` profile's conventional-dirs discovery (source_roots=["src"])
    # used to structurally EXCLUDE tests/ from the python import graph's own
    # node set — a limitation of `core/skills/import-graph.py::_collect_files`
    # (it used `source_roots` as a hard scan filter), not of test_map. That
    # made this fixture's "healthy" claim vacuous no matter what test_map
    # did: tests/test_app.py could never even become a depgraph node, so
    # production_to_tests could never be anything but empty — exactly the
    # kind of accidental vacuity AC-17 exists to rule out. KLC-122 review
    # round 1 (D-6/step-8) fixed `_collect_files` for real: it now always
    # includes every test-convention file regardless of `source_roots`, so
    # this fixture's own `generic` pin (set by `_copy_fixture` above) is
    # sufficient on its own — no per-test profile override needed any more.

    # tiny-py's real `from src.util import helper` / `from src.app import
    # run` package-style imports are not resolved by import-graph.py's
    # static python scanner (a further PRE-EXISTING limitation, unrelated to
    # this ticket: a package's own `__init__.py` is indexed only under its
    # `<pkg>.__init__` dotted name, since the last-segment fallback
    # deliberately skips `__init__` — never under the bare `<pkg>` name a
    # normal `from <pkg> import x` uses) — rewritten here, in this
    # ticket-local COPY only, to forms the scanner DOES resolve, so the
    # fixture's real content produces real edges instead of an accidental
    # empty test_map/module_edges that would trip AC-8's vacuity trigger
    # regardless of test_map's own correctness.
    app_init = root / "src" / "app" / "__init__.py"
    app_init.write_text(
        app_init.read_text(encoding="utf-8")
        .replace("from src.util import helper", "from src.util.helper import greet")
        .replace("helper.greet", "greet"),
        encoding="utf-8")
    test_app = root / "tests" / "test_app.py"
    test_app.write_text(
        test_app.read_text(encoding="utf-8")
        .replace("from src.app import run", "from src.app.__init__ import run"),
        encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m",
         "resolve imports for import-graph.py so tests/ participates in "
         "the python import graph")

    proc = _run_pipeline(root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    depgraph = _read(root, "depgraph.json")
    entry = depgraph["import_graphs"]["python"]
    assert entry.get("degraded") is False, entry
    assert entry["edges"], "expected a resolved import edge"

    # D-212 (review round 1, HIGH finding #1): AC-17's real claim is that the
    # SHIPPED `scripts/init.py --scan-only` pipeline alone — with no manual
    # out-of-band callgraph build, which is exactly what init.py/update.py
    # never do (Q-103) — produces no degraded flags on a healthy project.
    # The previous version of this test manually ran callgraph_python.py +
    # re-ran test_map.py/module_edges.py to dodge test_map's old
    # unconditional callgraph-absence trigger; that trigger is fixed
    # (index_coverage.callgraph_degraded_input, D-212), so the workaround is
    # gone and the artifacts init.py itself wrote are asserted directly —
    # including that test_map produced REAL, non-vacuous coverage, not just
    # a degraded:false flag with an empty production_to_tests underneath.
    test_map = _read(root, "test_map.json")
    assert test_map["degraded"] is False, test_map
    assert test_map["production_to_tests"]["src/app/__init__.py"]["coverage"] == "direct"
    assert _read(root, "module_edges.json")["degraded"] is False

    trace = _run_retriever(root, query="helper module logic")
    assert trace["degraded_inputs"] == []
    # Pinned literal (test-plan.md): the confidence this deterministic
    # pipeline produces for tiny-py's real content, from the shipped
    # `init.py --scan-only` pipeline alone — unaffected by this ticket,
    # since nothing here is degraded. A future regression that changes this
    # value without an explicit reason will be caught here.
    assert trace["confidence"] == "medium"
    assert trace["mode"] == "deterministic"
