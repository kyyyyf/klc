"""tests/integration/test_klc122_generic_profile_wiring.py — KLC-122 step-6 (AC-6).

Reproduces a real defect the ticket's profile-default flip (ue -> generic)
exposed on the branch's own full-suite run: `tests/integration/test_pipeline_wiring.py
::test_file_roles_and_symbol_usage_wired` started failing with `tested_by == []`.

Root cause: `core/skills/import-graph.py::_collect_files` uses `structural.json`'s
`source_roots` as a hard SCAN FILTER — "under source_roots, else (only if NO
source_root covers any file) fall back to the whole universe". Under the generic
profile's `conventional-dirs` module discovery, `source_roots` is a fixed
candidate list (`src`, `lib`, `pkg`, `internal`, `app`, `apps`, `services`) that
deliberately excludes `tests/` (tests are not source). Once a project has any one
of those directories (e.g. `pkg/`), `source_roots` is non-empty, the fallback
never fires, and every test file outside `source_roots` is silently dropped from
the import graph — no edge from the test file to the code it imports, so
`symbol_usage.py`'s degraded-mode `tested_by` (file-level import fallback) comes
back empty for every symbol.

This stayed hidden under the old `ue` default only by accident: a non-UE fixture
repo has no `*.Build.cs` file, so `build-cs` discovery mode's `source_roots`
resolved to `[]`, and "no source root covers any file" made the whole-universe
fallback fire on every run. The generic profile's `conventional-dirs` mode
routinely produces a non-empty `source_roots`, so the same latent gap now bites
every non-trivial project — exactly the invariant AC-6 calls out ("generic still
detects and indexes"), broadened here to the whole deterministic-view chain, not
just raw symbol extraction.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_skills = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
if str(_skills) not in sys.path:
    sys.path.insert(0, str(_skills))

import file_scanner  # noqa: E402
import dep_graph  # noqa: E402


def _load_import_graph_module():
    """import-graph.py's filename is hyphenated (not a valid module name),
    so callers reach it via subprocess in production (dep_graph.py); load it
    directly here to unit-test `_collect_files` in isolation."""
    path = _skills / "import-graph.py"
    spec = importlib.util.spec_from_file_location("_klc122_import_graph", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> None:
    import subprocess
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(x):\n    return x\n", encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(
        "from pkg.mod import public_fn\n\n"
        "def test_it():\n    assert public_fn(1) == 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def test_generic_profile_import_graph_includes_test_file_edges(tmp_path, monkeypatch):
    """AC-6: a test file importing a source-root file must produce an
    import-graph edge under the generic default — the deterministic-view
    chain (structural -> import-graph -> symbol_usage's tested_by) must
    survive the profile switch, not just raw C++/language symbol
    extraction."""
    root = _make_repo(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True)

    structural = file_scanner.scan(root)
    assert structural["profile"] == "generic"
    assert structural["source_roots"] == [{"path": "pkg", "module": "pkg"}], (
        "fixture assumption drifted — this test relies on a non-empty, "
        "test/-excluding source_roots to reproduce the bug"
    )
    (idx / "structural.json").write_text(json.dumps(structural), encoding="utf-8")

    result = dep_graph.build(root)
    py = result["import_graphs"]["python"]
    node_ids = {n["id"] for n in py["nodes"]}
    assert "tests/test_mod.py" in node_ids, (
        "tests/test_mod.py dropped from the import graph — source_roots is "
        "being used as a hard scan filter that silently excludes test files"
    )
    assert {"from": "tests/test_mod.py", "to": "pkg/mod.py"} in py["edges"], (
        "no edge from the test file to the file it imports — tested_by "
        "will come back empty downstream in symbol_usage.json"
    )


def test_collect_files_fallback_decision_ignores_test_hits(tmp_path):
    """Review round 1 MEDIUM: `_collect_files`'s own docstring says the
    source_roots-vs-fallback decision is 'computed over non-test hits
    only', but the code computed `under` from ALL hits, test files
    included. A test-convention-named file that happens to sit under a
    source_root (`pkg/test_helpers.py`) made `under` non-empty and
    suppressed the intended whole-universe fallback for a real non-test
    source file that sits under NO source_root (`weirdplace/mod.py`) —
    the reviewer's exact repro."""
    ig = _load_import_graph_module()
    universe = ["pkg/test_helpers.py", "weirdplace/mod.py"]
    source_roots = ["pkg"]
    collected = ig._collect_files(tmp_path, source_roots, (".py",), universe)
    rels = {str(p.relative_to(tmp_path)) for p in collected}
    assert rels == set(universe), (
        f"expected the whole-universe fallback to fire since no source_root "
        f"covers any NON-TEST file; got {rels}"
    )
