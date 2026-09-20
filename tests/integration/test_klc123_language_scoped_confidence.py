"""KLC-123 — scope the retriever's inventory-degradation cap to the languages
that actually bear on a given trace (AC-2 through AC-9).

KLC-106's `_cap_confidence` reads `index_coverage.artifact_degraded(inventory)`,
which ORs every per-language verdict in `inventory.json`'s `errors[]`: one
uncovered minority language (this repo's stray `.h`/`c` fixture, 0 files with
symbols out of 2) forces `confidence: low` on EVERY trace, including one whose
candidate files are entirely in a healthy, covered language. This module tests
the new `index_coverage.scoped_inventory_degradation` decision (AC-2..AC-5,
AC-9) directly, then `build_trace`'s wiring of it (AC-6, AC-7) is covered by
the second half of this file (added in step-2).

Verdict entries are hand-built rather than run through `index_coverage.verdict`
so each fixture's `degraded`/`universe` values are pinned and independent of
the live `index.coverage.min_ratio` settings state.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILLS = _FW_ROOT / "core" / "skills"
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import index_coverage  # noqa: E402
import settings  # noqa: E402
import validate_config as _vc  # noqa: E402


def _entry(lang: str, universe: int, degraded: bool) -> dict:
    return {"builder": f"inventory:{lang}", "artifact": "inventory.json",
            "observed": 0, "universe": universe, "ratio": 0.0,
            "degraded": degraded, "metric": "files-with-symbols",
            "threshold": 0.25, "reason": "test fixture"}


def _inventory(*entries) -> dict:
    return {"errors": list(entries)}


# --------------------------------------------------------------------- AC-2

def test_scoped_degradation_caps_when_candidate_language_degraded():
    inv = _inventory(_entry("python", 100, True))
    degraded, advisories, scoped = index_coverage.scoped_inventory_degradation(
        inv, {"python"})
    assert scoped is True
    assert degraded is True


# --------------------------------------------------------------------- AC-3

def test_scoped_degradation_advisory_not_cap_for_minority_language_outside_candidates():
    """99 covered python files + 1 uncovered-language (c) file: the candidate
    slice is entirely python, c sits outside candidate_languages and below the
    5% default share threshold — advisory, not a cap."""
    inv = _inventory(_entry("python", 99, False), _entry("c", 1, True))
    degraded, advisories, scoped = index_coverage.scoped_inventory_degradation(
        inv, {"python"})
    assert scoped is True
    assert degraded is False
    assert len(advisories) == 1
    assert "c" in advisories[0]
    assert "1.0%" in advisories[0]


# --------------------------------------------------------------------- AC-4

def test_scoped_degradation_caps_when_dominant_language_degraded_and_no_candidates():
    """No candidate files matched (empty set); the degraded language (c) is
    60% of the code universe — well above the 5% default floor — so the
    dominant-language fallback still caps."""
    inv = _inventory(_entry("python", 40, False), _entry("c", 60, True))
    degraded, advisories, scoped = index_coverage.scoped_inventory_degradation(
        inv, set())
    assert scoped is True
    assert degraded is True
    assert advisories == []


# --------------------------------------------------------------------- AC-5

def test_scoped_degradation_falls_back_when_inventory_has_no_per_language_verdicts():
    """An old-shape inventory (no `inventory:<lang>` entries in `errors[]`,
    the exact shape of KLC-106's own INVENTORY regression fixture) reports
    scoped=False so the caller falls back to `artifact_degraded` unchanged."""
    old_shape = {"symbols": [{"name": "f", "kind": "function",
                              "file": "a.py", "visibility": "public"}]}
    degraded, advisories, scoped = index_coverage.scoped_inventory_degradation(
        old_shape, {"python"})
    assert (degraded, advisories, scoped) == (False, [], False)

    empty_errors = {"errors": []}
    degraded2, advisories2, scoped2 = index_coverage.scoped_inventory_degradation(
        empty_errors, {"python"})
    assert (degraded2, advisories2, scoped2) == (False, [], False)


# --------------------------------------------------------------------- AC-9

@pytest.fixture
def scopes(tmp_path, monkeypatch):
    proj = tmp_path / "proj_config"
    fw = tmp_path / "fw_config"
    proj.mkdir()
    fw.mkdir()
    monkeypatch.setattr(settings, "_proj_config", lambda: proj)
    monkeypatch.setattr(settings, "_fw_config", lambda: fw)
    return proj, fw


def test_language_share_threshold_default_and_setting_override(scopes):
    proj, _fw = scopes
    # unset: the settings accessor is honest about absence...
    assert settings.index_coverage_language_share_threshold() is None
    # ...and index_coverage falls back to its own built-in default.
    assert index_coverage.language_share_threshold() == \
        index_coverage.DEFAULT_LANGUAGE_SHARE_THRESHOLD == 0.05

    # a project override, as the STRING "0.10" (the yaml-parser quirk
    # threshold_for already tolerates for index.coverage.min_ratio).
    (proj / "settings.yml").write_text(
        "index:\n  coverage:\n    language_share_threshold: \"0.10\"\n",
        encoding="utf-8")
    assert index_coverage.language_share_threshold() == 0.10


def test_validate_config_accepts_ratio_rejects_out_of_range_language_share_threshold(tmp_path):
    def _cfg(body):
        d = tmp_path / f"cfg_{hash(body) & 0xffff}"
        d.mkdir()
        (d / "settings.yml").write_text(body, encoding="utf-8")
        return d

    accepted = _vc.validate_settings(
        _cfg("index:\n  coverage:\n    language_share_threshold: 0.05\n"))
    assert not any("language_share_threshold" in w for w in accepted), accepted

    accepted_str = _vc.validate_settings(
        _cfg("index:\n  coverage:\n    language_share_threshold: \"0.05\"\n"))
    assert not any("language_share_threshold" in w for w in accepted_str), accepted_str

    for bad_body in (
        "index:\n  coverage:\n    language_share_threshold: 1.5\n",
        "index:\n  coverage:\n    language_share_threshold: -0.1\n",
        "index:\n  coverage:\n    language_share_threshold: true\n",
        "index:\n  coverage:\n    language_share_threshold: not-a-number\n",
    ):
        warns = _vc.validate_settings(_cfg(bad_body))
        assert any("language_share_threshold" in w for w in warns), (bad_body, warns)


# ==================================================================== step-2
# `build_trace`'s wiring of `scoped_inventory_degradation` (AC-6, AC-7).
# `build_trace` is loaded by path (hyphenated filename), same pattern as
# tests/integration/test_klc106_retriever_degraded.py's own `_load_skill()`.

import importlib.util as _ilu  # noqa: E402

_PR_SKILL = _SKILLS / "planning-retriever.py"


def _load_retriever():
    spec = _ilu.spec_from_file_location("planning_retriever_klc123", _PR_SKILL)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_pr = _load_retriever()

# A fixture known to reach top-level confidence "high" pre-cap — the SAME
# shape as tests/integration/test_klc106_retriever_degraded.py's own
# MODULES/FILE_ROLES_HEALTHY/MODULE_EDGES_HEALTHY/QUERY baseline.
_MODULES = {
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

_FILE_ROLES_PY = {
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

# The negative-twin fixture: the SAME files, but with a ".c" extension, so
# `_candidate_languages` resolves them to "c" instead of "python" — module
# membership is unaffected (module_membership.py resolves by the "core/intake/"
# directory prefix, not by extension).
_FILE_ROLES_C = {
    "files": {
        path.replace(".py", ".c"): rec
        for path, rec in _FILE_ROLES_PY["files"].items()
    }
}

_MODULE_EDGES_HEALTHY = {
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
_TEST_MAP = {"production_to_tests": {}, "module_to_tests": {}}
_QUERY = "add a new validation rule for incoming tickets"


def test_build_trace_candidate_language_healthy_not_capped_by_unrelated_minority_language():
    """AC-6, AC-7: the candidate slice is entirely python (healthy); the
    inventory's only degraded language is 'c', a 1%-share repo minority
    outside the candidate languages — no cap, and the advisory names 'c'."""
    inventory = _inventory(_entry("python", 99, False), _entry("c", 1, True))
    trace = _pr.build_trace(_QUERY, "deterministic", _MODULES, _FILE_ROLES_PY,
                            _MODULE_EDGES_HEALTHY, _TEST_MAP, inventory)
    assert "inventory.json" not in trace["degraded_inputs"], trace["degraded_inputs"]
    assert trace["confidence"] == "high", trace
    assert any("c" in a for a in trace["coverage_advisories"]), trace["coverage_advisories"]


def test_build_trace_candidate_slice_entirely_minority_uncovered_language_still_capped():
    """AC-6 negative twin: the candidate slice is entirely 'c' — a degraded
    AND repo-minority language — but membership in candidate_languages
    overrides the dominant-share fallback, so it still caps."""
    inventory = _inventory(_entry("python", 99, False), _entry("c", 1, True))
    trace = _pr.build_trace(_QUERY, "deterministic", _MODULES, _FILE_ROLES_C,
                            _MODULE_EDGES_HEALTHY, _TEST_MAP, inventory)
    assert "inventory.json" in trace["degraded_inputs"], trace["degraded_inputs"]
    assert trace["confidence"] == "low", trace


def test_build_trace_coverage_advisories_field_empty_when_nothing_degraded():
    """AC-7 baseline: a fully healthy inventory produces coverage_advisories == []."""
    inventory = _inventory(_entry("python", 99, False), _entry("c", 1, False))
    trace = _pr.build_trace(_QUERY, "deterministic", _MODULES, _FILE_ROLES_PY,
                            _MODULE_EDGES_HEALTHY, _TEST_MAP, inventory)
    assert trace["coverage_advisories"] == []
    assert trace["degraded_inputs"] == []


# ============================================================ step-5 (review-fix)
# Review round-1 drift finding F-1 (MEDIUM): AC-6/step-2 derived
# candidate_languages from EVERY matched (score > 0) file, including a bare
# weak path-segment/keyword hit on a fixture/test file that never surfaces in
# either presented slice — exactly the collision that broke the literal AC-8
# query live (build-log.md D-123-2: "coverage" weak-matching
# tests/fixtures/rules/coverage/sample.{h,cpp,rs}). Operator ruling: narrow
# candidate_languages to the trace's PRESENTED slices
# (files_likely_to_edit ∪ files_to_read_first) instead of any score>0 match.
# These two tests pin that narrowing with the exact "weak-token-collision"
# shape the live incident exhibited, plus its twin (the same collision, but
# the file DOES land in a presented slice, where it must still cap).

# The base python fixture plus one extra 'c' file that weak-matches the query
# token "tickets" via its own PATH ONLY (no keywords/symbols) — the same
# mechanism as the live "coverage" collision — but is ORPHANED (its directory
# is not owned by any module in _MODULES), so it can never become eligible
# for either presented slice regardless of its eligible_as_primary flag.
_FILE_ROLES_PY_WITH_ORPHAN_C_COLLISION = {
    "files": {
        **_FILE_ROLES_PY["files"],
        "tests/fixtures/tickets/sample.c": {
            "module_name": None,
            "roles": ["domain_logic"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": [], "symbols": [], "confidence": "low",
        },
    }
}

# The same weak-token-collision file, but placed under "core/intake/" (a
# module _MODULES actually owns) and left eligible_as_primary + domain_logic,
# so it DOES land in the presented slices (files_to_read_first and
# files_likely_to_edit both admit it).
_FILE_ROLES_PY_WITH_ELIGIBLE_C_COLLISION = {
    "files": {
        **_FILE_ROLES_PY["files"],
        "core/intake/tickets_sample.c": {
            "module_name": "intake",
            "roles": ["domain_logic"],
            "is_entrypoint": False, "is_test": False, "is_generated": False,
            "is_config": False, "eligible_as_primary": True,
            "keywords": [], "symbols": [], "confidence": "low",
        },
    }
}


def test_build_trace_weak_token_collision_outside_presented_slices_not_capped():
    """AC-6 (narrowed scope, review round-1 F-1): a weak path-segment
    collision ("tickets" matching tests/fixtures/tickets/sample.c, a 'c'
    file) gives that file score > 0 — it IS a member of the old, unscoped
    `matched` set — but it is orphaned (no module owns
    tests/fixtures/tickets/) so it never reaches files_to_read_first or
    files_likely_to_edit. Its language must therefore NOT enter
    candidate_languages, and the degraded 'c' verdict (a repo-minority,
    below the default 5% share floor) must advise, not cap."""
    inventory = _inventory(_entry("python", 99, False), _entry("c", 1, True))
    trace = _pr.build_trace(_QUERY, "deterministic", _MODULES,
                            _FILE_ROLES_PY_WITH_ORPHAN_C_COLLISION,
                            _MODULE_EDGES_HEALTHY, _TEST_MAP, inventory)
    assert "tests/fixtures/tickets/sample.c" not in trace["files_to_read_first"], trace
    assert "tests/fixtures/tickets/sample.c" not in trace["files_likely_to_edit"], trace
    assert "inventory.json" not in trace["degraded_inputs"], trace["degraded_inputs"]
    assert trace["confidence"] == "high", trace
    assert any("'c'" in a and "not capped" in a for a in trace["coverage_advisories"]), \
        trace["coverage_advisories"]


def test_build_trace_weak_token_collision_inside_presented_slices_still_capped():
    """AC-6 twin: the SAME weak path-segment collision, but the 'c' file
    lives under a module _MODULES owns (core/intake/) and is
    eligible_as_primary + domain_logic, so it DOES land in the presented
    slices. Its language ('c') must enter candidate_languages, and the
    degraded 'c' verdict must cap — membership in the presented slice
    overrides the dominant-share fallback, same as the pre-existing AC-6
    negative twin above."""
    inventory = _inventory(_entry("python", 99, False), _entry("c", 1, True))
    trace = _pr.build_trace(_QUERY, "deterministic", _MODULES,
                            _FILE_ROLES_PY_WITH_ELIGIBLE_C_COLLISION,
                            _MODULE_EDGES_HEALTHY, _TEST_MAP, inventory)
    assert "core/intake/tickets_sample.c" in (
        trace["files_to_read_first"] + trace["files_likely_to_edit"]), trace
    assert "inventory.json" in trace["degraded_inputs"], trace["degraded_inputs"]
    assert trace["confidence"] == "low", trace
