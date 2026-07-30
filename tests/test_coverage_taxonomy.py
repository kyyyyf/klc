#!/usr/bin/env python3
"""tests/test_coverage_taxonomy.py — the coverage taxonomy's three forms stay honest.

KLC-086 (E-01) ships the requirements-coverage taxonomy as three coupled artifacts,
shaped exactly like the constitution (KLC-082): the machine form
`config/coverage-taxonomy.yml`, the ONE reader `core/skills/coverage_taxonomy.py`, and
the human narrative `docs/coverage-taxonomy.md`. These tests are the guardrail that keeps
them honest: the YAML carries the ten spec-kit categories with valid min_track floors and
the eight ISO/IEC 25010 NFR sub-characteristics; the reader is package-safe and
degrade-not-fail; and the doc↔YAML id sets never drift.

Run:  python -m pytest tests/test_coverage_taxonomy.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import importlib.util  # noqa: E402
import _yaml  # noqa: E402  (the real runtime parser — step-1 reads the YAML directly)
import coverage_taxonomy  # noqa: E402  (the loader under test)

YML = FW_ROOT / "config" / "coverage-taxonomy.yml"
MD = FW_ROOT / "docs" / "coverage-taxonomy.md"

# The ten spec-kit coverage categories, in the order they ship, each with its
# min_track floor from the epic's track-applicability table.
EXPECTED_IDS = [
    "functional-scope",
    "domain-data-model",
    "interaction-ux",
    "nfr",
    "integration-external",
    "edge-failure",
    "constraints-tradeoffs",
    "terminology",
    "completion-signals",
    "misc-placeholders",
]
EXPECTED_FLOORS = {
    "functional-scope": "XS",
    "domain-data-model": "S",
    "interaction-ux": "S",
    "nfr": "M",
    "integration-external": "M",
    "edge-failure": "S",
    "constraints-tradeoffs": "M",
    "terminology": "M",
    "completion-signals": "XS",
    "misc-placeholders": "XS",
}
# The eight ISO/IEC 25010 product-quality characteristics, in standard order.
ISO_25010 = [
    "functional-suitability",
    "performance-efficiency",
    "compatibility",
    "usability",
    "reliability",
    "security",
    "maintainability",
    "portability",
]
VALID_TRACKS = {"XS", "S", "M", "L"}


def _yml_doc() -> dict:
    """Parse the taxonomy YAML with the in-repo minimal parser (what the runtime uses)."""
    return _yaml.parse(YML.read_text(encoding="utf-8"))


def _yml_categories() -> list[dict]:
    return _yml_doc()["categories"]


# --- step-1: the YAML data file (shape over the real parser) -----------------

def test_ten_spec_kit_categories_present():
    """The taxonomy declares exactly the ten spec-kit categories, in file order,
    each with a stable id / name / description / min_track (AC-4)."""
    cats = _yml_categories()
    assert [c["id"] for c in cats] == EXPECTED_IDS, "category ids / order drifted"
    for c in cats:
        assert isinstance(c.get("id"), str) and c["id"].strip(), c
        assert isinstance(c.get("name"), str) and c["name"].strip(), c
        assert isinstance(c.get("description"), str) and c["description"].strip(), c
        assert isinstance(c.get("min_track"), str) and c["min_track"].strip(), c
        assert c["min_track"] == EXPECTED_FLOORS[c["id"]], c


def test_yaml_well_formed_under_both_parsers():
    """The minimal in-repo parser and PyYAML must AGREE — so the file is valid
    standard YAML AND consumable by the stdlib-only runtime path (C-001 fidelity,
    mirrors tests/test_constitution.py::test_yaml_well_formed_under_both_parsers)."""
    import yaml  # dev/test dependency only

    text = YML.read_text(encoding="utf-8")
    minimal = _yaml.parse(text)
    standard = yaml.safe_load(text)
    assert minimal == standard
    assert isinstance(minimal.get("categories"), list)
    assert minimal["categories"], "coverage taxonomy has no categories"


def test_nfr_has_eight_iso25010_subcharacteristics():
    """The non-functional category enumerates the eight ISO/IEC 25010 quality
    characteristics as named sub-characteristics (AC-5)."""
    nfr = next(c for c in _yml_categories() if c["id"] == "nfr")
    assert nfr.get("sub_characteristics") == ISO_25010


def test_every_category_has_valid_min_track():
    """Every category carries a min_track floor drawn from the XS/S/M/L model (AC-6)."""
    for c in _yml_categories():
        assert c.get("min_track") in VALID_TRACKS, c


# --- step-2: the reader skill (load / ids / by_id / for_track / categories) ---

def _write_taxonomy(path: Path, ids_floors: dict[str, str]) -> None:
    """Write a minimal but valid taxonomy YAML for override/isolation tests."""
    lines = ["schema_version: 1", "categories:"]
    for cid, floor in ids_floors.items():
        lines += [
            f"  - id: {cid}",
            f"    name: {cid}",
            f"    description: test category {cid}",
            f"    min_track: {floor}",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_reader_api_surface():
    """The reader exposes load / ids / by_id / for_track / categories, each
    returning the documented shape (AC-2)."""
    doc = coverage_taxonomy.load()
    assert isinstance(doc, dict) and doc.get("schema_version") == 1
    cats = coverage_taxonomy.categories()
    assert isinstance(cats, list) and cats and all(isinstance(c, dict) for c in cats)
    assert coverage_taxonomy.ids() == EXPECTED_IDS
    # by_id round-trips for a known id and returns None for an unknown one.
    assert coverage_taxonomy.by_id("nfr")["id"] == "nfr"
    assert coverage_taxonomy.by_id("no-such-category") is None
    ft = coverage_taxonomy.for_track("L")
    assert isinstance(ft, list) and {c["id"] for c in ft} == set(EXPECTED_IDS)


def test_load_returns_versioned_categories():
    """load() reads config/coverage-taxonomy.yml and returns its schema_version
    plus a non-empty category list (AC-1)."""
    doc = coverage_taxonomy.load()
    assert doc["schema_version"] == 1
    assert isinstance(doc["categories"], list) and doc["categories"]
    assert [c["id"] for c in doc["categories"]] == EXPECTED_IDS


def test_for_track_floor_filtering():
    """for_track returns exactly the categories whose min_track floor is at or
    below the requested track; the sets are monotonic across XS ⊂ S ⊂ M ⊂ L,
    and each track never returns a category floored above it (AC-3)."""
    by_track = {t: {c["id"] for c in coverage_taxonomy.for_track(t)}
                for t in ("XS", "S", "M", "L")}
    order = {"XS": 0, "S": 1, "M": 2, "L": 3}
    # XS returns only XS-floor categories.
    assert by_track["XS"] == {cid for cid, f in EXPECTED_FLOORS.items() if f == "XS"}
    # Monotone nesting.
    assert by_track["XS"] <= by_track["S"] <= by_track["M"] <= by_track["L"]
    # L returns every category.
    assert by_track["L"] == set(EXPECTED_IDS)
    # No category is ever returned at a track below its floor.
    for t, got in by_track.items():
        for cid in got:
            assert order[EXPECTED_FLOORS[cid]] <= order[t], (t, cid)
    # An unknown track string degrades to empty, never raises.
    assert coverage_taxonomy.for_track("XXL") == []


def test_package_safe_import():
    """Imported as `core.skills.coverage_taxonomy` (a package module, with
    core/skills NOT on sys.path) the reader still resolves the in-repo _yaml
    parser and works — a naive `import _yaml` would grab PyYAML's C accelerator
    (no `parse`). It must also coexist with constitution.py's private _yaml
    module in one process without a name collision (AC-2)."""
    import constitution  # noqa: E402  the sibling reader; must coexist

    skills = str(FW_ROOT / "core" / "skills")
    saved = list(sys.path)
    try:
        sys.path[:] = [p for p in sys.path if p != skills]
        if str(FW_ROOT) not in sys.path:
            sys.path.insert(0, str(FW_ROOT))
        spec = importlib.util.spec_from_file_location(
            "core.skills.coverage_taxonomy",
            FW_ROOT / "core" / "skills" / "coverage_taxonomy.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.ids() == EXPECTED_IDS
    finally:
        sys.path[:] = saved
    # Both readers still work in-process — no shared-module clobber.
    assert coverage_taxonomy.ids() == EXPECTED_IDS
    assert constitution.ids()  # non-empty


def test_project_override_shadows_framework_copy(tmp_path, monkeypatch):
    """A `.klc/config/coverage-taxonomy.yml` wins over the framework copy,
    exactly like models.yml (AC-1)."""
    proj = tmp_path / "klc-config"
    fw = tmp_path / "fw"
    proj.mkdir()
    (fw / "config").mkdir(parents=True)
    _write_taxonomy(proj / "coverage-taxonomy.yml", {"override-only": "XS"})
    _write_taxonomy(fw / "config" / "coverage-taxonomy.yml", {"framework-only": "XS"})
    monkeypatch.setattr(coverage_taxonomy, "klc_config_dir", lambda: proj)
    monkeypatch.setattr(coverage_taxonomy, "framework_root", lambda: fw)
    assert coverage_taxonomy.taxonomy_path() == proj / "coverage-taxonomy.yml"
    assert coverage_taxonomy.ids() == ["override-only"]


def test_degrade_on_missing_file(tmp_path, monkeypatch):
    """When the taxonomy file is absent, the consumer-facing accessors degrade to
    empty / None without raising; only load() raises (AC-7)."""
    missing = tmp_path / "nope" / "coverage-taxonomy.yml"
    monkeypatch.setattr(coverage_taxonomy, "taxonomy_path", lambda: missing)
    assert coverage_taxonomy.categories() == []
    assert coverage_taxonomy.ids() == []
    assert coverage_taxonomy.by_id("nfr") is None
    assert coverage_taxonomy.for_track("L") == []
    import pytest
    with pytest.raises(FileNotFoundError):
        coverage_taxonomy.load()


def test_degrade_on_malformed_file(tmp_path, monkeypatch):
    """A file present but malformed / with no categories degrades the accessors to
    empty / None (same path as absent); load() raises ValueError (AC-7)."""
    bad = tmp_path / "coverage-taxonomy.yml"
    bad.write_text("schema_version: 1\ncategories:\n", encoding="utf-8")  # no categories
    monkeypatch.setattr(coverage_taxonomy, "taxonomy_path", lambda: bad)
    assert coverage_taxonomy.categories() == []
    assert coverage_taxonomy.ids() == []
    assert coverage_taxonomy.by_id("nfr") is None
    assert coverage_taxonomy.for_track("M") == []
    import pytest
    with pytest.raises(ValueError):
        coverage_taxonomy.load()


def test_for_track_degrades_on_nonscalar_min_track(tmp_path, monkeypatch):
    """A malformed (override) taxonomy whose category carries a NON-SCALAR
    min_track (e.g. a list) must not crash for_track with an unhashable-key
    TypeError — that category is treated as an unknown floor and excluded, the
    valid categories still return (degrade-not-fail, codex-P2)."""
    bad = tmp_path / "coverage-taxonomy.yml"
    bad.write_text(
        "schema_version: 1\n"
        "categories:\n"
        "  - id: good\n"
        "    name: good\n"
        "    description: a valid category\n"
        "    min_track: M\n"
        "  - id: broken\n"
        "    name: broken\n"
        "    description: non-scalar floor\n"
        "    min_track: [XS]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(coverage_taxonomy, "taxonomy_path", lambda: bad)
    got = coverage_taxonomy.for_track("M")  # must not raise
    assert {c["id"] for c in got} == {"good"}


def test_degrade_on_directory_path(tmp_path, monkeypatch):
    """taxonomy_path() gates on .exists(), which is True for a directory or an
    unreadable file, so read_text() raises IsADirectoryError / PermissionError
    (both OSError). The degrading accessors must absorb those too (LOW-4), not
    only FileNotFoundError."""
    as_dir = tmp_path / "coverage-taxonomy.yml"
    as_dir.mkdir()  # a directory at the resolved path
    monkeypatch.setattr(coverage_taxonomy, "taxonomy_path", lambda: as_dir)
    assert coverage_taxonomy.categories() == []
    assert coverage_taxonomy.for_track("M") == []
    assert coverage_taxonomy.ids() == []
    assert coverage_taxonomy.by_id("nfr") is None


def test_single_reader_no_second_parser():
    """The taxonomy file is opened / parsed by exactly one module — the reader.
    No consumer re-parses it (single-source-of-truth, AC-9). Guard by grepping the
    framework source for the taxonomy filename: only coverage_taxonomy.py may name it."""
    core = FW_ROOT / "core"
    referencing = set()
    for py in core.rglob("*.py"):
        if "coverage-taxonomy.yml" in py.read_text(encoding="utf-8"):
            referencing.add(py.name)
    assert referencing == {"coverage_taxonomy.py"}, referencing


# --- step-3: docs/coverage-taxonomy.md ↔ YAML lockstep -----------------------

import re  # noqa: E402


def test_doc_yaml_lockstep():
    """Every category id in the YAML appears as a `### `<id>`` anchor in
    docs/coverage-taxonomy.md and every documented id exists in the YAML — set
    equality in both directions, so the two forms can never drift (AC-8)."""
    assert MD.exists() and MD.stat().st_size > 0
    doc = MD.read_text(encoding="utf-8")
    yaml_ids = set(coverage_taxonomy.ids())
    doc_ids = set(re.findall(r"^###\s+`([a-z0-9-]+)`", doc, re.M))
    missing_in_md = yaml_ids - doc_ids
    extra_in_md = doc_ids - yaml_ids
    assert not missing_in_md, f"ids in yml but not documented in md: {sorted(missing_in_md)}"
    assert not extra_in_md, f"ids documented in md but not in yml: {sorted(extra_in_md)}"
    # The doc must also carry the ISO 25010 NFR expansion (the eight names).
    for name in ISO_25010:
        assert name in doc, f"ISO 25010 characteristic missing from doc: {name}"
    # Floors are load-bearing for E-05, so the doc's declared `- **min_track** X`
    # under each `### `<id>`` section must equal the YAML floor for that id. This
    # fails loudly if a floor is flipped in only one of the two forms (MEDIUM-1).
    sections = re.split(r"^###\s+`([a-z0-9-]+)`\s*$", doc, flags=re.M)
    doc_floors: dict[str, str] = {}
    for i in range(1, len(sections), 2):
        cid, body = sections[i], sections[i + 1]
        m = re.search(r"^-\s+\*\*min_track\*\*\s+([A-Za-z]+)\s*$", body, re.M)
        assert m, f"no `- **min_track** X` line documented for `{cid}`"
        doc_floors[cid] = m.group(1)
    assert set(doc_floors) == yaml_ids, "doc floor sections drifted from ids"
    for cid, floor in doc_floors.items():
        yaml_floor = coverage_taxonomy.by_id(cid)["min_track"]
        assert floor == yaml_floor, (
            f"min_track drift for `{cid}`: doc={floor} yaml={yaml_floor}"
        )
