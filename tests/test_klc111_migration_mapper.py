"""KLC-111 step-3 — the legacy-name mapper: one pure function turns one
legacy `affected_modules` name into a verdict (kept, mapped, ambiguous or
unmappable), using only that name and `modules.json` (AC-7, AC-8).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import module_vocabulary as _mv  # noqa: E402

MODULES = {
    "modules": [
        {"name": "core/skills", "path": "core/skills/",
         "files": ["core/skills/module_membership.py", "core/skills/scope_delta.py"]},
        {"name": "klc-plugin/skills/run", "path": "klc-plugin/skills/run/",
         "files": ["klc-plugin/skills/run/SKILL.md"]},
        {"name": "klc-plugin/skills/discuss-feature", "path": "klc-plugin/skills/discuss-feature/",
         "files": ["klc-plugin/skills/discuss-feature/SKILL.md"]},
    ],
}


def test_maps_legacy_name_by_exact_module_name():
    """AC-7: a legacy name that is already a module name (`core/skills`) maps
    verbatim — the ticket's slice is left byte-identical."""
    v = _mv.map_legacy_name("core/skills", MODULES)
    assert v["modules"] == ["core/skills"]
    new, verdicts = _mv.migrate_modules(["core/skills"], MODULES)
    assert new == ["core/skills"]
    assert verdicts[0]["name"] == "core/skills"


def test_maps_legacy_name_by_tracked_file_path():
    """AC-7: a legacy name that is itself a tracked file path resolves
    through `file_to_module` to the module owning that file."""
    name = "core/skills/module_membership.py"
    v = _mv.map_legacy_name(name, MODULES)
    assert v["status"] == "mapped"
    assert v["modules"] == ["core/skills"]


def test_maps_legacy_name_scope_delta_by_basename_stem_to_core_skills():
    """AC-7: `scope_delta` (a bare file stem, the spec's own worked example)
    maps to `core/skills`, the module owning `scope_delta.py`."""
    v = _mv.map_legacy_name("scope_delta", MODULES)
    assert v["status"] == "mapped"
    assert v["modules"] == ["core/skills"]


def test_name_matching_none_of_the_three_rules_is_left_untouched_and_listed_unmappable():
    """AC-7 negative twin: a name matching none of the three rules (e.g.
    `knowledge`, a `.klc/` state directory) is left untouched in the ticket's
    slice and reported unmappable in the run report."""
    v = _mv.map_legacy_name("knowledge", MODULES)
    assert v["status"] == "unmappable"
    assert v["modules"] == []
    new, verdicts = _mv.migrate_modules(["knowledge"], MODULES)
    assert new == ["knowledge"], "unmappable names pass through untouched"
    assert verdicts[0]["status"] == "unmappable"


def test_directory_prefix_only_name_klc_plugin_skills_reported_ambiguous_not_expanded():
    """AC-8 negative/fail-closed twin: `klc-plugin/skills` matches only as a
    directory prefix of two child modules — it is refused, reported
    ambiguous with its candidates, and never auto-expanded."""
    v = _mv.map_legacy_name("klc-plugin/skills", MODULES)
    assert v["status"] == "ambiguous"
    assert v["modules"] == []
    assert v["candidates"] == ["klc-plugin/skills/discuss-feature", "klc-plugin/skills/run"]
    new, verdicts = _mv.migrate_modules(["klc-plugin/skills"], MODULES)
    assert new == ["klc-plugin/skills"], "an ambiguous name must not be expanded"
    assert verdicts[0]["status"] == "ambiguous"


def test_name_that_is_both_a_directory_prefix_and_a_unique_stem_match_maps_by_stem():
    """AC-8 (review-fix MEDIUM, `[!DECISION D-111-2]`): AC-8 refuses to
    auto-map a name that matches ONLY as a directory prefix. A name that is
    BOTH a directory prefix of other modules AND a unique tracked-file-stem
    match is not "only" a prefix hit, so it must map by the stem rule, not
    be refused as ambiguous. Repro: modules `widget/foo`/`widget/bar` make
    `widget` a directory prefix, but `src/widget.py` also makes it a unique
    stem match to `src` — the stem/path rules now run BEFORE the
    prefix-ambiguity check, so `widget` maps to `["src"]`."""
    modules = {"modules": [
        {"name": "widget/foo", "path": "widget/foo/", "files": ["widget/foo/a.py"]},
        {"name": "widget/bar", "path": "widget/bar/", "files": ["widget/bar/b.py"]},
        {"name": "src", "path": "src/", "files": ["src/widget.py"]},
    ]}
    v = _mv.map_legacy_name("widget", modules)
    assert v["status"] == "mapped", v
    assert v["modules"] == ["src"], v


def test_name_that_is_a_directory_prefix_and_a_non_unique_stem_match_stays_ambiguous():
    """AC-8 (review-fix MEDIUM round 2, `[!DECISION D-111-6]`): D-111-2's
    "path/stem beats prefix-ambiguity" override applies ONLY when the
    stem/path hit is a SINGLE unique module. A name that is a directory
    prefix AND a stem match to TWO OR MORE unrelated modules is not a
    precise resolution either — `migrate_modules` would otherwise fan the
    multi-module list into `affected_modules`, exactly the imprecision
    AC-8/D-007 forbid. Repro: `widget/foo`/`widget/bar` make `widget` a
    directory prefix; `alpha` (owning a file whose stem is `widget`) and
    `beta` (ditto) make it a NON-unique stem match — with a competing
    prefix hit present, the verdict must fall through to `ambiguous` with
    the prefix's own candidates, not fan out to `['alpha', 'beta']`."""
    modules = {"modules": [
        {"name": "widget/foo", "path": "widget/foo/", "files": ["widget/foo/a.py"]},
        {"name": "widget/bar", "path": "widget/bar/", "files": ["widget/bar/b.py"]},
        {"name": "alpha", "path": "alpha/", "files": ["alpha/widget.py"]},
        {"name": "beta", "path": "beta/", "files": ["beta/widget.py"]},
    ]}
    v = _mv.map_legacy_name("widget", modules)
    assert v["status"] == "ambiguous", v
    assert v["modules"] == [], v
    assert v["candidates"] == ["widget/bar", "widget/foo"], v


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
