#!/usr/bin/env python3
"""tests/test_elicitation_techniques.py — the elicitation catalog + picker + gate.

KLC-087 (E-06) ships a data-driven catalog of named elicitation techniques as three
coupled pieces, mirroring the coverage taxonomy (KLC-086): the machine form
`config/elicitation-techniques.csv`, the ONE reader/picker
`core/skills/elicitation_techniques.py`, and this guardrail. The CSV carries the trimmed
serious method set across exactly six categories; the reader is package-safe and
degrade-not-fail; `pick` keeps the catalog out of the caller's context (≤5, never whole);
and `should_offer` is the HARD track-gate that never fires on XS/S by default. The skill
exposes selection only — there is deliberately no apply/run entrypoint.

Run:  python -m pytest tests/test_elicitation_techniques.py -v
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import importlib.util  # noqa: E402
import elicitation_techniques  # noqa: E402  (the reader/picker under test)

CSV = FW_ROOT / "config" / "elicitation-techniques.csv"

REQUIRED_COLUMNS = ["id", "name", "category", "description", "output_pattern"]

# The six fixed categories with the trimmed roster's per-category counts.
EXPECTED_CATEGORY_COUNTS = {
    "core": 7,
    "framing": 4,
    "risk": 5,
    "creative": 5,
    "collaboration": 4,
    "technical": 5,
}

# The named serious anchors that MUST resolve to a row, keyed by their stable id.
ANCHOR_IDS = [
    "5-whys",
    "first-principles",
    "socratic",
    "pre-mortem",
    "inversion",
    "steelman",
    "assumption-audit",
    "abstraction-laddering",
    "six-thinking-hats",
    "scamper",
    "second-order",
    "source-triangulation",
    "red-team-blue-team",
    "stakeholder-round-table",
]


def _csv_rows() -> list[dict]:
    """Read the CSV with the stdlib parser — what the runtime reader uses (step-1 reads
    it directly, before the reader module exists)."""
    with CSV.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# --- step-1: the CSV data file (shape over the stdlib csv parser) -------------

def test_csv_has_required_columns():
    """Every catalog row carries id/name/category/description/output_pattern, none
    empty (AC-3)."""
    rows = _csv_rows()
    assert rows, "elicitation-techniques.csv has no rows"
    for row in rows:
        for col in REQUIRED_COLUMNS:
            assert col in row, f"missing column {col!r} in {row}"
            assert isinstance(row[col], str) and row[col].strip(), (col, row)


def test_six_categories_with_expected_counts():
    """The catalog holds the trimmed roster spread across exactly the six categories
    core/framing/risk/creative/collaboration/technical with the expected counts (AC-4)."""
    rows = _csv_rows()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    assert counts == EXPECTED_CATEGORY_COUNTS, counts
    assert sum(counts.values()) == 30


def test_named_anchor_methods_present():
    """The named serious anchors each resolve to a row by stable id (AC-4, Q-001)."""
    ids = {row["id"] for row in _csv_rows()}
    missing = [a for a in ANCHOR_IDS if a not in ids]
    assert not missing, f"anchor techniques missing from catalog: {missing}"


# --- step-2: the reader/picker skill (load / by_category / pick) --------------

def _write_csv(path: Path, rows: list[dict]) -> None:
    """Write a minimal valid catalog CSV for override / isolation tests."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _row(cid: str, category: str) -> dict:
    return {
        "id": cid,
        "name": cid.replace("-", " ").title(),
        "category": category,
        "description": f"test technique {cid}",
        "output_pattern": "a → b → c",
    }


def test_load_returns_rows():
    """load() reads config/elicitation-techniques.csv and returns non-empty method
    rows, each carrying the five columns (AC-1)."""
    rows = elicitation_techniques.load()
    assert isinstance(rows, list) and rows
    assert len(rows) == 30
    for row in rows:
        for col in REQUIRED_COLUMNS:
            assert row.get(col), (col, row)


def test_reader_api_surface():
    """The reader exposes load / by_category / pick as callables returning the
    documented shapes (AC-2)."""
    for name in ("load", "by_category", "pick"):
        assert callable(getattr(elicitation_techniques, name)), name
    assert isinstance(elicitation_techniques.load(), list)
    assert isinstance(elicitation_techniques.by_category("core"), list)
    assert isinstance(elicitation_techniques.pick("risk"), list)


def test_package_safe_import():
    """Imported as `core.skills.elicitation_techniques` (a package module, with
    core/skills NOT on sys.path) the reader still resolves core.shared.paths and
    works. It must also coexist with coverage_taxonomy.py and constitution.py in one
    process without a name collision (AC-2)."""
    import constitution  # noqa: E402  sibling readers; must coexist
    import coverage_taxonomy  # noqa: E402

    skills = str(FW_ROOT / "core" / "skills")
    saved = list(sys.path)
    try:
        sys.path[:] = [p for p in sys.path if p != skills]
        if str(FW_ROOT) not in sys.path:
            sys.path.insert(0, str(FW_ROOT))
        spec = importlib.util.spec_from_file_location(
            "core.skills.elicitation_techniques",
            FW_ROOT / "core" / "skills" / "elicitation_techniques.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert len(mod.load()) == 30
    finally:
        sys.path[:] = saved
    # All three readers still work in-process — no shared-module clobber.
    assert len(elicitation_techniques.load()) == 30
    assert coverage_taxonomy.ids()
    assert constitution.ids()


def test_project_override_shadows_framework_copy(tmp_path, monkeypatch):
    """A `.klc/config/elicitation-techniques.csv` wins over the framework copy,
    exactly like taxonomy_path() resolves the override (AC-1)."""
    proj = tmp_path / "klc-config"
    fw = tmp_path / "fw"
    proj.mkdir()
    (fw / "config").mkdir(parents=True)
    _write_csv(proj / "elicitation-techniques.csv", [_row("override-only", "core")])
    _write_csv(fw / "config" / "elicitation-techniques.csv", [_row("framework-only", "core")])
    monkeypatch.setattr(elicitation_techniques, "klc_config_dir", lambda: proj)
    monkeypatch.setattr(elicitation_techniques, "framework_root", lambda: fw)
    assert elicitation_techniques.techniques_path() == proj / "elicitation-techniques.csv"
    assert [r["id"] for r in elicitation_techniques.load()] == ["override-only"]


def test_by_category_filters():
    """by_category returns only rows of the requested category, and [] for an
    unknown category name (AC-4, degrade-not-fail edge)."""
    for cat, count in EXPECTED_CATEGORY_COUNTS.items():
        got = elicitation_techniques.by_category(cat)
        assert {r["category"] for r in got} == {cat}, cat
        assert len(got) == count, (cat, len(got))
    assert elicitation_techniques.by_category("no-such-category") == []


def test_pick_returns_at_most_five():
    """pick(context) returns at most five rows with the default n, and honours a
    smaller/larger explicit n (AC-5)."""
    assert len(elicitation_techniques.pick("risk")) <= 5
    assert len(elicitation_techniques.pick("design")) <= 5
    assert len(elicitation_techniques.pick("")) <= 5
    assert len(elicitation_techniques.pick("risk", n=3)) <= 3
    # n larger than the relevant pool returns the whole pool, still ≤ full catalog.
    big = elicitation_techniques.pick("risk", n=99)
    assert len(big) < 30


def test_pick_never_returns_whole_catalog():
    """The pick result is a strict subset of load() — the catalog never enters the
    caller's context whole (AC-5)."""
    all_ids = {r["id"] for r in elicitation_techniques.load()}
    for ctx in ("risk", "launch", "code", "design", "stakeholders", "ideation", "", "unknown"):
        got_ids = {r["id"] for r in elicitation_techniques.pick(ctx)}
        assert got_ids < all_ids, ctx  # strict subset
        assert len(got_ids) <= 5, ctx


def test_pick_draws_from_context_categories():
    """A risk/launch context biases the draw toward risk/technical rows; the picker
    selects categories then hands back rows drawn only from them (AC-5)."""
    for ctx in ("risk", "launch"):
        cats = {r["category"] for r in elicitation_techniques.pick(ctx)}
        assert cats <= {"risk", "technical"}, (ctx, cats)
        assert cats  # non-empty
    ideation = {r["category"] for r in elicitation_techniques.pick("ideation")}
    assert ideation <= {"creative", "framing"}, ideation


def test_degrade_on_missing_file(tmp_path, monkeypatch):
    """When the CSV is absent, the consumer-facing accessors degrade to [] without
    raising; only load() raises (AC-6)."""
    missing = tmp_path / "nope" / "elicitation-techniques.csv"
    monkeypatch.setattr(elicitation_techniques, "techniques_path", lambda: missing)
    assert elicitation_techniques.by_category("core") == []
    assert elicitation_techniques.pick("risk") == []
    import pytest
    with pytest.raises((OSError, ValueError)):
        elicitation_techniques.load()


def test_degrade_on_malformed_file(tmp_path, monkeypatch):
    """A file present but malformed / with no data rows degrades the accessors to []
    (same path as absent); load() raises (AC-6)."""
    bad = tmp_path / "elicitation-techniques.csv"
    bad.write_text("not,a,catalog\ngarbage,without,id\n", encoding="utf-8")
    monkeypatch.setattr(elicitation_techniques, "techniques_path", lambda: bad)
    assert elicitation_techniques.by_category("core") == []
    assert elicitation_techniques.pick("risk") == []
    import pytest
    with pytest.raises(ValueError):
        elicitation_techniques.load()


def test_load_drops_rows_missing_required_columns(tmp_path, monkeypatch):
    """A project-override row with id/category but an empty/missing name, description,
    or output_pattern is DROPPED, not served — so pick()/by_category() never hand a
    consumer a dict missing a contract key (codex-P2). The good rows stay usable."""
    bad = tmp_path / "elicitation-techniques.csv"
    good = _row("good-one", "core")
    with bad.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerow(good)
        # id + category present, description blank -> incomplete, must be dropped.
        writer.writerow({"id": "no-desc", "name": "No Desc", "category": "core",
                         "description": "", "output_pattern": "a → b"})
    monkeypatch.setattr(elicitation_techniques, "techniques_path", lambda: bad)
    ids = {r["id"] for r in elicitation_techniques.load()}
    assert ids == {"good-one"}, ids
    for accessor in (elicitation_techniques.by_category("core"),
                     elicitation_techniques.pick("code")):
        assert {r["id"] for r in accessor} == {"good-one"}
        for row in accessor:
            for col in REQUIRED_COLUMNS:
                assert col in row and row[col], (col, row)  # every key present + non-empty


def test_degrade_on_csv_error(tmp_path, monkeypatch):
    """A parser-level malformation (an oversized field, > the stdlib csv field limit)
    raises csv.Error — a direct Exception subclass, NOT OSError/ValueError. The
    degrading accessors must absorb it too (fresh-MEDIUM), not only the bad-header
    ValueError that test_degrade_on_malformed_file covers."""
    import csv as _csv
    huge = "x" * (_csv.field_size_limit() + 1)
    bad = tmp_path / "elicitation-techniques.csv"
    bad.write_text(
        "id,name,category,description,output_pattern\n"
        f"big,Big,core,{huge},a → b\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(elicitation_techniques, "techniques_path", lambda: bad)
    # Sanity: load() genuinely hits csv.Error on this input.
    import pytest
    with pytest.raises(_csv.Error):
        elicitation_techniques.load()
    # The consumer-facing accessors must degrade, not propagate.
    assert elicitation_techniques.by_category("core") == []
    assert elicitation_techniques.pick("risk") == []


# --- step-3: the HARD track-gate + never-apply-without-a-yes contract ---------

def test_gate_offers_on_M_and_L():
    """should_offer returns True on M and L — the picker is offered on the larger
    tracks by default (AC-7)."""
    assert elicitation_techniques.should_offer("M") is True
    assert elicitation_techniques.should_offer("L") is True


def test_gate_blocks_XS_and_S_without_flag():
    """should_offer returns False on XS and S with no flagged ambiguity — the
    fail-closed case, so the picker never fires on small tickets by default (AC-7,
    C-003)."""
    assert elicitation_techniques.should_offer("XS") is False
    assert elicitation_techniques.should_offer("S") is False
    assert elicitation_techniques.should_offer("XS", flagged_ambiguity=False) is False
    assert elicitation_techniques.should_offer("S", flagged_ambiguity=False) is False


def test_gate_flagged_ambiguity_overrides_track():
    """A flagged real ambiguity is the sole escape onto XS/S — should_offer returns
    True regardless of track when flagged_ambiguity is set (AC-7, C-003)."""
    assert elicitation_techniques.should_offer("XS", flagged_ambiguity=True) is True
    assert elicitation_techniques.should_offer("S", flagged_ambiguity=True) is True
    # The flag does not weaken the M/L default either.
    assert elicitation_techniques.should_offer("M", flagged_ambiguity=True) is True


def test_gate_rejects_unknown_track():
    """An unknown track string with no flag never opens the gate — unknown is
    fail-closed, not fail-open (AC-7)."""
    assert elicitation_techniques.should_offer("XXL") is False
    assert elicitation_techniques.should_offer("") is False
    # The flag is still the sole escape even for an unknown track.
    assert elicitation_techniques.should_offer("XXL", flagged_ambiguity=True) is True


def test_no_apply_entrypoint():
    """The module exports selection only (load/by_category/pick/should_offer) and no
    apply/run/execute callable — never-apply-without-a-yes (AC-8, C-004)."""
    # should_offer is part of the documented selection surface (AC-2).
    assert callable(elicitation_techniques.should_offer)
    forbidden = ("apply", "run", "execute", "apply_technique", "run_technique",
                 "execute_technique", "invoke")
    for name in forbidden:
        attr = getattr(elicitation_techniques, name, None)
        assert not callable(attr), f"module must not export an apply-style callable: {name!r}"
    # No public callable name even hints at applying/running a technique.
    for name in dir(elicitation_techniques):
        if name.startswith("_"):
            continue
        if not callable(getattr(elicitation_techniques, name)):
            continue
        lowered = name.lower()
        assert not any(verb in lowered for verb in ("apply", "execute", "invoke")), name
