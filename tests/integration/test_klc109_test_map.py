"""tests/integration/test_klc109_test_map.py — KLC-109 step-4: test_map maps
production to tests with no callgraph and no import graph, from filename
convention alone, taking its file universe from KLC-105's
`structural["files_rel"]` seam.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2] / "core" / "skills"
sys.path.insert(0, str(_SKILLS))

import test_map as tm  # noqa: E402
import test_conventions as tc  # noqa: E402

_ENGINE_MANIFEST = (
    Path(__file__).resolve().parents[1] / "fixtures" / "klc109-engine-profile" / "manifest.yml"
)

# One root-relative pair per AC-2 language, all under "proj/" so a single
# file-stem module ("proj") attributes every one of them (KLC-109 needs no
# depgraph/callgraph at all to find these pairs).
_LANG_PAIRS = {
    "python": ("proj/foo.py", "proj/tests/test_foo.py"),
    "js-ts": ("proj/Foo.tsx", "proj/Foo.test.tsx"),
    "go": ("proj/foo.go", "proj/foo_test.go"),
    "rust": ("proj/foo.rs", "proj/foo_test.rs"),
    "java-kotlin": ("proj/Foo.java", "proj/FooTest.java"),
    "csharp": ("proj/Foo.cs", "proj/FooTests.cs"),
    "ruby": ("proj/foo.rb", "proj/foo_spec.rb"),
    "cpp": ("proj/foo.cpp", "proj/foo_test.cpp"),
}
_MODULES = {"modules": [{"name": "proj", "path": "proj"}]}


def _structural():
    files = [p for pair in _LANG_PAIRS.values() for p in pair]
    return {"files_rel": files, "root": "/fake/root"}


def test_module_to_tests_populated_from_files_rel_convention_only():
    """AC-7: build_test_map given a structural["files_rel"]-shaped universe
    with empty depgraph/callgraph still yields a non-empty module_to_tests,
    including the Foo.tsx/Foo.test.tsx pair and one pair per AC-2 language."""
    result = tm.build_test_map(_structural(), {}, _MODULES, None)
    assert result["module_to_tests"], "expected a non-empty module_to_tests"
    tests_in_module = result["module_to_tests"]["proj"]
    for lang, (prod, test) in _LANG_PAIRS.items():
        assert test in tests_in_module, (lang, test)
        entry = result["production_to_tests"][prod]
        assert entry["coverage"] == "module", (lang, entry)
        row = next(r for r in entry["tests"] if r["test_file"] == test)
        assert row["relationship"] == "name_similarity", (lang, row)


def test_universe_unavailable_degrades_to_empty_layer_with_error_note():
    """AC-7 fail-closed: no files_rel and no universe= — an errors[] entry
    naming structural.files_rel, an empty convention layer, no exception and
    NO filesystem walk."""
    result = tm.build_test_map({}, {}, {}, None)
    assert result["production_to_tests"] == {}
    assert result["module_to_tests"] == {}
    assert any("structural.files_rel" in e for e in result["errors"]), result["errors"]


def test_shared_module_files_are_not_self_referential_tests_in_the_map():
    """Code-review MEDIUM (D-109-11): core/skills/test_map.py and
    core/skills/test_conventions.py — a bare python `test_*.py`/`test_*.py`
    basename with no `map.py`/`conventions.py` sibling anywhere in the
    universe — must NOT classify themselves as tests in build_test_map's own
    convention layer (the split-brain the MEDIUM finding named: the ack gate
    was fixed in round 1, but test_map's own map stayed split). Their real
    test files (which DO reference AC ids and DO import the module) are the
    ones that show up as tests; the two framework modules show up as
    ordinary, uncovered production files instead of vanishing from
    production_to_tests entirely."""
    structural = {
        "files_rel": [
            "core/skills/test_map.py", "core/skills/test_conventions.py",
            "tests/test_test_conventions.py",
            "tests/integration/test_klc109_test_map.py",
        ],
        "root": "/fake/root",
    }
    modules = {"modules": [{"name": "core/skills", "path": "core/skills/"},
                           {"name": "tests", "path": "tests/"}]}
    result = tm.build_test_map(structural, {}, modules, None)
    # The two framework modules are production files here, not tests.
    assert "core/skills/test_map.py" in result["production_to_tests"]
    assert "core/skills/test_conventions.py" in result["production_to_tests"]
    assert not any(
        r["test_file"] in ("core/skills/test_map.py", "core/skills/test_conventions.py")
        for entry in result["production_to_tests"].values()
        for r in entry["tests"]
    )
    # And the map is genuinely non-empty (AC-7's own honesty requirement) —
    # the real test files under tests/ are recognised via the directory
    # signal and land at module level.
    assert result["module_to_tests"], "expected a non-empty module_to_tests"


def test_out_of_universe_graph_nodes_stay_dropped():
    """AC-7/F-1 regression guard against KLC-105: a depgraph node outside
    files_rel stays dropped, with KLC-105's own note wording, after KLC-109's
    convention layer is added."""
    structural = {"files_rel": ["proj/Foo.tsx", "proj/Foo.test.tsx"],
                 "root": "/fake/root"}
    depgraph = {"import_graphs": {"python": {
        "nodes": [{"id": "outside/ghost.py"}], "edges": []}}}
    result = tm.build_test_map(structural, depgraph, _MODULES, None)
    assert "outside/ghost.py" not in result["production_to_tests"]
    assert any("out-of-universe" in n and "files_rel" in n for n in result["notes"]), \
        result["notes"]


def test_convention_edge_is_medium_confidence_source_convention():
    """AC-8: a convention-only edge records source: convention,
    confidence: medium."""
    result = tm.build_test_map(_structural(), {}, _MODULES, None)
    prod, test = _LANG_PAIRS["js-ts"]
    row = next(r for r in result["production_to_tests"][prod]["tests"]
              if r["test_file"] == test)
    assert row["source"] == "convention"
    assert row["confidence"] == "medium"


def test_callgraph_edge_upgrades_same_pair_to_high_confidence():
    """AC-8: the same production/test pair ALSO has a callgraph edge -> the
    edge reports source: callgraph, confidence: high, and the medium
    convention edge for that pair is superseded, not duplicated."""
    prod, test = _LANG_PAIRS["js-ts"]
    callgraph = {"symbols": {f"{prod}::render": {
        "file": prod, "called_by": [f"{test}::test_render"]}}}
    result = tm.build_test_map(_structural(), {}, _MODULES, callgraph)
    rows = [r for r in result["production_to_tests"][prod]["tests"]
           if r["test_file"] == test]
    assert len(rows) == 1, "must not duplicate the row for the same pair"
    assert rows[0]["source"] == "callgraph"
    assert rows[0]["confidence"] == "high"


def test_adding_callgraph_does_not_remove_convention_only_edges():
    """AC-8: a different pair covered ONLY by convention (no callgraph edge
    for it) is unchanged when a callgraph is supplied for another pair."""
    js_prod, js_test = _LANG_PAIRS["js-ts"]
    go_prod, go_test = _LANG_PAIRS["go"]
    callgraph = {"symbols": {f"{js_prod}::render": {
        "file": js_prod, "called_by": [f"{js_test}::test_render"]}}}
    result = tm.build_test_map(_structural(), {}, _MODULES, callgraph)
    go_row = next(r for r in result["production_to_tests"][go_prod]["tests"]
                 if r["test_file"] == go_test)
    assert go_row["source"] == "convention"
    assert go_row["confidence"] == "medium"


def test_ue_spec_cpp_pairs_with_production_through_active_table():
    """AC-5 (F-2 end-to-end #2): the D-OP-1 synthetic engine-style fixture
    (standing in for the deleted profiles/ue/manifest.yml — test-plan.md's
    Revision note) makes test_map pair Source/Foo/Private/FooSpec.cpp with
    Source/Foo/Private/Foo.cpp; under builtin_table() it does not."""
    import yaml  # dev/test dependency only — imported lazily so the per-test
    # conftest fixture (_restore_real_pyyaml) has already run and undone any
    # core/shared/yaml.py shadow a full-suite run may have left in sys.modules
    manifest = yaml.safe_load(_ENGINE_MANIFEST.read_text(encoding="utf-8"))
    engine_table = tc.table_from_manifest(manifest)
    structural = {
        "files_rel": ["Source/Foo/Private/Foo.cpp", "Source/Foo/Private/FooSpec.cpp"],
        "root": "/fake/root",
    }
    modules = {"modules": [{"name": "engine", "path": "Source"}]}

    engine_result = tm.build_test_map(structural, {}, modules, None, table=engine_table)
    entry = engine_result["production_to_tests"]["Source/Foo/Private/Foo.cpp"]
    assert entry["coverage"] == "module"
    assert any(r["test_file"] == "Source/Foo/Private/FooSpec.cpp" for r in entry["tests"])

    builtin_result = tm.build_test_map(structural, {}, modules, None,
                                       table=tc.builtin_table())
    builtin_entry = builtin_result["production_to_tests"]["Source/Foo/Private/Foo.cpp"]
    assert builtin_entry["coverage"] == "none"
    assert builtin_entry["tests"] == []
