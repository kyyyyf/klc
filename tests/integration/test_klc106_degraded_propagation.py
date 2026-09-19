"""KLC-106 step-5 — module_edges, symbol_usage and test_map name their
degraded inputs (AC-8).

Each consumer sets `degraded: true` and a `degraded_inputs` list naming every
artifact it consumes that is either itself `degraded: true` or present but
empty of the evidence this consumer needs. Every existing error string and
fallback path is preserved verbatim (regression list in test-plan.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

_skills = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
if str(_skills) not in sys.path:
    sys.path.insert(0, str(_skills))

import module_edges as me  # noqa: E402
import symbol_usage as su  # noqa: E402
import test_map as tm  # noqa: E402


MODS = {"modules": [
    {"name": "modA", "path": "src/a", "files": ["src/a/foo.py"],
     "depends_on": [], "depended_by": []},
    {"name": "modB", "path": "src/b", "files": ["src/b/bar.py"],
     "depends_on": [], "depended_by": []},
]}


def _depgraph(edges=None, lang="python", degraded=False):
    entry = {"edges": edges or [], "nodes": []}
    if degraded:
        entry["degraded"] = True
    return {"import_graphs": {lang: entry}}


def test_module_edges_symbol_usage_test_map_set_degraded_inputs_from_upstream_degraded_artifact():
    # module_edges: depgraph itself flagged degraded (below-threshold node
    # coverage) even though it still carries an edge.
    depgraph = _depgraph([{"from": "src/b/bar.py", "to": "src/a/foo.py"}], degraded=True)
    result = me.build_detailed_edges(MODS, depgraph, callgraph=None)
    assert result["degraded"] is True
    assert "depgraph.json" in result["degraded_inputs"]

    # symbol_usage: callgraph itself degraded.
    inventory = {"symbols": [
        {"name": "f", "kind": "function", "file": "src/a/foo.py", "line": 1,
         "signature": "f()", "visibility": "public", "source_of_truth": "regex",
         "lang": "python", "rule": "r"},
    ]}
    callgraph = {"symbols": {}, "errors": [
        {"builder": "callgraph:python", "artifact": "callgraph/python.json",
         "metric": "callgraph-symbols", "observed": 0, "universe": 1,
         "ratio": 0.0, "threshold": 0.25, "degraded": True, "reason": "x"},
    ]}
    su_result = su.build_symbol_usage(inventory, MODS, callgraph, depgraph={})
    assert su_result["degraded"] is True
    assert "callgraph" in su_result["degraded_inputs"]

    # test_map: depgraph degraded.
    structural = {"files_rel": ["src/a/foo.py", "src/b/bar_test.py"]}
    tm_result = tm.build_test_map(structural, depgraph, MODS, callgraph=None)
    assert tm_result["degraded"] is True
    assert "depgraph.json" in tm_result["degraded_inputs"]


def test_consumers_set_degraded_inputs_when_upstream_present_but_empty_of_needed_evidence():
    # module_edges: depgraph present, healthy (no degraded flag), but zero edges.
    depgraph_empty = _depgraph([], degraded=False)
    result = me.build_detailed_edges(MODS, depgraph_empty, callgraph=None)
    assert result["degraded"] is True
    assert "depgraph.json" in result["degraded_inputs"]

    # symbol_usage: callgraph present but empty AND no import-graph fallback.
    inventory = {"symbols": [
        {"name": "f", "kind": "function", "file": "src/a/foo.py", "line": 1,
         "signature": "f()", "visibility": "public", "source_of_truth": "regex",
         "lang": "python", "rule": "r"},
    ]}
    empty_callgraph = {"symbols": {}}
    su_result = su.build_symbol_usage(inventory, MODS, empty_callgraph, depgraph={})
    assert su_result["degraded"] is True
    assert "callgraph" in su_result["degraded_inputs"]

    # test_map: depgraph present but vacuous (no candidate files at all).
    structural = {"files_rel": []}
    tm_result = tm.build_test_map(structural, {}, MODS, callgraph=None)
    assert tm_result["degraded"] is True
    assert "depgraph.json" in tm_result["degraded_inputs"]


def test_consumer_tolerates_older_artifact_missing_degraded_field():
    """A404: an artifact written before KLC-106 has no `degraded` key at all —
    the reader treats it as not-degraded, never KeyError, never True."""
    old_depgraph = {"import_graphs": {"python": {
        "edges": [{"from": "src/b/bar.py", "to": "src/a/foo.py"}], "nodes": []}}}
    result = me.build_detailed_edges(MODS, old_depgraph, callgraph=None)
    assert result["degraded"] is False
    assert result["degraded_inputs"] == []

    inventory = {"symbols": [
        {"name": "f", "kind": "function", "file": "src/a/foo.py", "line": 1,
         "signature": "f()", "visibility": "public", "source_of_truth": "regex",
         "lang": "python", "rule": "r"},
    ]}
    old_callgraph = {"symbols": {"src/a/foo.py::f": {
        "kind": "function", "file": "src/a/foo.py", "calls": [], "called_by": []}}}
    su_result = su.build_symbol_usage(inventory, MODS, old_callgraph, depgraph={})
    assert su_result["degraded"] is False
    assert su_result["degraded_inputs"] == []

    structural = {"files_rel": ["src/a/foo.py", "src/b/bar_test.py"]}
    tm_result = tm.build_test_map(structural, old_depgraph, MODS, callgraph=old_callgraph)
    assert tm_result["degraded"] is False
    assert tm_result["degraded_inputs"] == []


# ------------------------------------------------------- D-212 (review rework)
#
# Review round 1, HIGH finding #1 + drift F-1: test_map named "callgraph" as
# a degraded input on bare ABSENCE, regardless of whether the fallback
# signals (direct_import / name_similarity) already produced real coverage.
# Since scripts/init.py and scripts/update.py never build a callgraph
# (Q-103), this forced degraded:true — and therefore confidence:low via the
# retriever's cap — on every ordinary index, forever. The fix: callgraph
# absence only counts as a degraded input when the consumer's OWN output is
# genuinely vacuous given the available inputs (index_coverage.
# callgraph_degraded_input, D-212), never on mere absence when something
# else already answered the question.

def test_test_map_does_not_flag_bare_callgraph_absence_when_fallback_produced_coverage():
    """Reproduces the reviewer's empirical repro: a healthy depgraph edge
    (test imports production file) plus callgraph=None must NOT set
    degraded:true — the direct_import relationship already gives real,
    useful coverage; a callgraph could only ever ADD to it, never replace
    the fact that the answer is already known."""
    depgraph = _depgraph([{"from": "tests/test_foo.py", "to": "src/a/foo.py"}])
    structural = {"files_rel": ["src/a/foo.py", "tests/test_foo.py"]}
    result = tm.build_test_map(structural, depgraph, MODS, callgraph=None)
    assert result["production_to_tests"]["src/a/foo.py"]["coverage"] == "direct"
    assert result["degraded"] is False
    assert result["degraded_inputs"] == []


def test_test_map_still_flags_callgraph_when_genuinely_vacuous():
    """The two AC-16 falsifying fixtures must keep flagging: when NOTHING —
    not depgraph, not name-similarity, not callgraph — produced any
    file-specific coverage, the absence is real information and must still
    be named."""
    structural = {"files_rel": []}
    result = tm.build_test_map(structural, {}, MODS, callgraph=None)
    assert result["degraded"] is True
    assert "callgraph" in result["degraded_inputs"]


def test_module_edges_flags_callgraph_when_genuinely_vacuous_like_its_siblings():
    """Review MEDIUM finding: module_edges no longer hardcodes vacuous=False
    for callgraph. When its own evidence (depgraph) is ALSO empty, an
    absent callgraph is named exactly like symbol_usage/test_map already do
    for the identical condition — no more unexplained 3-way asymmetry."""
    depgraph_empty = _depgraph([], degraded=False)
    result = me.build_detailed_edges(MODS, depgraph_empty, callgraph=None)
    assert result["degraded"] is True
    assert "callgraph" in result["degraded_inputs"]


def test_module_edges_does_not_flag_callgraph_when_depgraph_already_covers_it():
    """The mirror case: depgraph alone already produced a real cross-module
    edge, so a merely-absent callgraph is not named — matching test_map's
    behaviour on the same shared rule."""
    depgraph = _depgraph([{"from": "src/b/bar.py", "to": "src/a/foo.py"}])
    result = me.build_detailed_edges(MODS, depgraph, callgraph=None)
    assert result["degraded"] is False
    assert "callgraph" not in result["degraded_inputs"]


def test_symbol_usage_present_but_empty_callgraph_always_flags_even_with_fallback():
    """A callgraph that actually RAN and came back empty is a real, concrete
    degradation — unlike bare absence, it always counts, regardless of
    whether a file-level import fallback also exists (D-212's "a callgraph
    was expected" half of the rule)."""
    inventory = {"symbols": [
        {"name": "f", "kind": "function", "file": "src/a/foo.py", "line": 1,
         "signature": "f()", "visibility": "public", "source_of_truth": "regex",
         "lang": "python", "rule": "r"},
    ]}
    empty_callgraph = {"symbols": {}}
    depgraph_with_fallback = _depgraph(
        [{"from": "src/b/bar.py", "to": "src/a/foo.py"}])
    su_result = su.build_symbol_usage(
        inventory, MODS, empty_callgraph, depgraph_with_fallback)
    assert su_result["degraded"] is True
    assert "callgraph" in su_result["degraded_inputs"]
