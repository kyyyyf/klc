"""KLC-106 step-6 — the retriever reports its evidence and stops claiming
high confidence anywhere without it (AC-9, AC-10, AC-11).

`build_trace` is a pure function; every test here calls it directly (loaded
by path, same as tests/integration/test_planning_retriever.py, since the
module's filename is hyphenated and cannot be `import`ed normally).
"""
from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-retriever.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_retriever_klc106", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_skill()

# A fixture known to reach top-level confidence "high" (top_score >= 4 and
# files_likely_to_edit non-empty) — mirrors
# tests/integration/test_planning_retriever.py's MODULES/FILE_ROLES/QUERY,
# which test_query_ranks_matching_module_first already proves lands there.
MODULES = {
    "modules": [
        {"name": "intake", "path": "core/intake/",
         "primary_entrypoints": ["core/intake/parser.py"],
         "public_surfaces": ["core/intake/validation.py"],
         "test_files": ["tests/test_intake.py"],
         "summary": "Parses and validates incoming ticket descriptions.",
         "keywords": ["ticket", "intake", "validation", "parse"]},
        {"name": "routing", "path": "core/routing/",
         "summary": "Routes requests to the right handler.",
         "keywords": ["route", "dispatch"]},
    ],
    "files": {},
}

FILE_ROLES_HEALTHY = {
    "files": {
        "core/intake/validation.py": {
            "module_name": "intake",
            "roles": ["public_surface", "domain_logic"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["validate", "ticket", "schema"],
            "symbols": ["validate_ticket", "ValidationResult"],
            "confidence": "high"},
        "core/intake/parser.py": {
            "module_name": "intake",
            "roles": ["entrypoint", "domain_logic"],
            "is_entrypoint": True, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["parse", "ticket"],
            "symbols": ["parse_ticket"], "confidence": "high"},
        "core/intake/schema.py": {
            "module_name": "intake",
            "roles": ["types"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": ["schema", "ticket"],
            "symbols": ["TicketSchema"], "confidence": "high"},
    }
}

FILE_ROLES_VACUOUS = {
    "files": {
        path: {**rec, "roles": []}
        for path, rec in FILE_ROLES_HEALTHY["files"].items()
    }
}

MODULE_EDGES_HEALTHY = {
    "edges": [
        {"from": "intake", "to": "routing",
         "edge_types": ["runtime_import"],
         "evidence": [{"source": "import_graph", "type": "runtime_import",
                       "from": "core/intake/validation.py",
                       "to": "core/routing/router.py", "confidence": "high"}],
         "evidence_count": 2, "confidence": "high",
         "direction": "outbound", "expand_by_default": True},
    ]
}
MODULE_EDGES_EMPTY = {"edges": []}
TEST_MAP = {"production_to_tests": {}, "module_to_tests": {}}
INVENTORY = {"symbols": [
    {"name": "validate_ticket", "kind": "function",
     "file": "core/intake/validation.py", "visibility": "public"},
]}
QUERY = "add a new validation rule for incoming tickets"


def _trace(module_edges, roles):
    return _mod.build_trace(QUERY, "deterministic", MODULES, roles,
                            module_edges, TEST_MAP, INVENTORY)


# Baseline sanity: this combination must actually reach "high" pre-cap, or
# the whole property test below is vacuous.
def test_baseline_fixture_reaches_high_confidence_uncapped():
    trace = _trace(MODULE_EDGES_HEALTHY, FILE_ROLES_HEALTHY)
    assert trace["confidence"] == "high"
    assert trace["degraded_inputs"] == []


_EDGE_VARIANTS = {"healthy": MODULE_EDGES_HEALTHY, "empty": MODULE_EDGES_EMPTY,
                  "absent": None}
_ROLES_VARIANTS = {"healthy": FILE_ROLES_HEALTHY, "vacuous": FILE_ROLES_VACUOUS}


def _generated_cases():
    """Every (edges, roles) combination, including the one that would
    otherwise land in the top_score >= 4 / files_likely_to_edit branch."""
    return list(itertools.product(_EDGE_VARIANTS, _ROLES_VARIANTS))


def test_confidence_never_high_when_degraded_inputs_nonempty_property():
    for edge_key, roles_key in _generated_cases():
        trace = _trace(_EDGE_VARIANTS[edge_key], _ROLES_VARIANTS[roles_key])
        if trace["degraded_inputs"]:
            assert trace["confidence"] != "high", (edge_key, roles_key, trace)
        elif edge_key == "healthy" and roles_key == "healthy":
            assert trace["confidence"] == "high"


def test_primary_modules_confidence_never_high_when_degraded_inputs_nonempty_property():
    """Review F-4 sibling: the SAME generated combinations, asserted over
    primary_modules[*].confidence rather than the top-level field — the
    second site build_trace can produce a 'high' from."""
    for edge_key, roles_key in _generated_cases():
        trace = _trace(_EDGE_VARIANTS[edge_key], _ROLES_VARIANTS[roles_key])
        if trace["degraded_inputs"]:
            assert all(m["confidence"] != "high" for m in trace["primary_modules"]), (
                edge_key, roles_key, trace["primary_modules"])
        elif edge_key == "healthy" and roles_key == "healthy":
            assert any(m["confidence"] == "high" for m in trace["primary_modules"])


# --------------------------------------------------------------------- AC-11

def test_mode_name_match_only_when_module_edges_contributes_no_edges():
    trace = _trace(MODULE_EDGES_EMPTY, FILE_ROLES_HEALTHY)
    assert trace["mode"] == "name-match-only"
    assert any("module_edges" in r for r in trace["reasons"])


def test_mode_stays_default_when_module_edges_has_edges():
    trace = _trace(MODULE_EDGES_HEALTHY, FILE_ROLES_HEALTHY)
    assert trace["mode"] == "deterministic"


# ------------------------------------------------------- D-212 (review rework)

def test_confidence_not_capped_when_test_map_callgraph_is_merely_absent():
    """Review round 1, HIGH finding #1: end-to-end reproduction through the
    REAL test_map.build_test_map (not a hand-built dict with no `degraded`
    key), mirroring the reviewer's empirical repro exactly — a healthy
    depgraph edge, healthy module_edges and healthy file_roles, callgraph
    absent. Before the D-212 fix, test_map unconditionally set
    degraded:true on bare callgraph absence, which the retriever's cap then
    forced to confidence:low regardless of how healthy everything else was."""
    import importlib.util as _ilu
    tm_path = _FW_ROOT / "core" / "skills" / "test_map.py"
    spec = _ilu.spec_from_file_location("test_map_klc106_retriever_check", tm_path)
    tm = _ilu.module_from_spec(spec)
    spec.loader.exec_module(tm)

    depgraph = {"import_graphs": {"python": {
        "edges": [{"from": "tests/test_validation.py",
                  "to": "core/intake/validation.py"}],
        "nodes": [], "degraded": False}}}
    structural = {"files_rel": ["core/intake/validation.py",
                                "tests/test_validation.py"]}
    real_test_map = tm.build_test_map(structural, depgraph, MODULES, callgraph=None)
    assert real_test_map["degraded"] is False, real_test_map

    trace = _mod.build_trace(QUERY, "deterministic", MODULES, FILE_ROLES_HEALTHY,
                             MODULE_EDGES_HEALTHY, real_test_map, INVENTORY)
    assert trace["degraded_inputs"] == []
    assert trace["confidence"] == "high"
