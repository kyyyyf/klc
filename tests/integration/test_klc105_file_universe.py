"""KLC-105 step-1 — unit coverage for the shared file-universe resolver.

``core/skills/file_universe.py`` is the ONE resolver + closure predicate every
index builder consumes (AC-1, AC-9). These three rows pin the resolver itself,
which the acceptance rows (test_klc105_scan_only_closure.py etc.) exercise only
indirectly. Appended to test-plan.md's acceptance table under AC-1 and AC-9.
"""
from __future__ import annotations

import sys
from pathlib import Path

_skills = Path(__file__).resolve().parents[2] / "core" / "skills"
sys.path.insert(0, str(_skills))
import file_universe  # noqa: E402


def test_resolve_prefers_structural_files_rel(tmp_path):
    """AC-1/C-003: a structural dict carrying files_rel AND a matching root is
    adopted verbatim, with source == 'structural.files_rel' — a builder that has
    structural.json available must not recompute git state."""
    root = tmp_path / "proj"
    root.mkdir()
    structural = {"root": str(root), "files_rel": ["b.py", "a.py", "a.py"]}
    result = file_universe.resolve(root, structural=structural)
    assert result["source"] == "structural.files_rel"
    # sorted + deduped-by-sort (a.py appears twice in input; resolve does not dedupe
    # beyond what sorted() does, but the acceptance test only requires exact adoption
    # of the declared list content — sorted here for a deterministic assertion).
    assert result["files"] == sorted(["b.py", "a.py", "a.py"])


def test_resolve_ignores_structural_from_a_different_root(tmp_path):
    """D-002: a structural.json describing a DIFFERENT root is not adopted; the
    universe is recomputed. Without this guard a builder run against a temp fixture
    would inherit the ambient project's universe and every fixture-based closure
    assertion would be validated against the wrong set."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "real.txt").write_text("hi", encoding="utf-8")
    other_root = tmp_path / "elsewhere"
    structural = {"root": str(other_root), "files_rel": ["not-really-here.py"]}
    result = file_universe.resolve(root, structural=structural)
    assert result["source"] != "structural.files_rel"
    assert "not-really-here.py" not in result["files"]
    assert any("different root" in n for n in result["notes"])


def test_out_of_universe_flags_non_members():
    """AC-9: the shared closure predicate returns exactly the injected non-members,
    sorted, and an empty list for a closed set. This is the single predicate
    planning_validate (AC-7) and the integration suite (AC-6) both import."""
    universe = ["a.py", "b.py", "c.py"]
    assert file_universe.out_of_universe(
        ["a.py", "z.py", "b.py", "y.py"], universe) == ["y.py", "z.py"]
    assert file_universe.out_of_universe(["a.py", "b.py"], universe) == []
    assert file_universe.out_of_universe([], universe) == []


def test_collect_index_paths_uses_path_field_for_a_path_carrying_graph():
    """D-003 (design/options.md): the closure predicate must check the `path`
    field for path-carrying graphs (e.g. madge), not the node `id` — a
    module-scoped graph's id can be a MODULE NAME (e.g. parsed from a build
    manifest's file stem), never a repo-relative path, so a closure check over
    `id` tests the wrong field entirely and would flag a real, in-universe
    build-manifest file as an out-of-universe violation (or miss a genuine
    violation whose module name happens to collide with an in-universe path)."""
    depgraph = {
        "import_graphs": {
            "modgraph": {
                "tool": "grep *.module-manifest",
                "nodes": [
                    {"id": "MyModule", "path": "Source/MyModule/MyModule.module-manifest"},
                    {"id": "ExternalDep", "path": ""},
                ],
                "edges": [{"from": "MyModule", "to": "ExternalDep"}],
            }
        }
    }
    categories = file_universe.collect_index_paths(depgraph=depgraph)
    # The real file path must be collected from the node, not just its
    # module-name id (edges still carry module-name from/to keys, which is
    # outside this fix's scope — only the node-path branch is under test).
    assert "Source/MyModule/MyModule.module-manifest" in categories["depgraph"]
    # A node with an empty path (external dependency) falls back to its id.
    assert "ExternalDep" in categories["depgraph"]
