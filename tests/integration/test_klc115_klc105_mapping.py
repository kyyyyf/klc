"""KLC-115 step-2 (AC-17) + design-addendum: the Evidence parser proved
against the three real, unedited Evidence sections this project has written.
All three tests are READ-ONLY — none writes to any ticket artifact.
"""
from __future__ import annotations

import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import evidence_gate as eg  # noqa: E402

TICKETS_DIR = FRAMEWORK_ROOT / ".klc" / "tickets"


def _evidence_section(ticket: str) -> str:
    text = (TICKETS_DIR / ticket / "build-log.md").read_text(encoding="utf-8")
    section = eg.evidence_section(text)
    assert section is not None, f"{ticket}/build-log.md has no ## Evidence section"
    return section


def test_klc105_build_log_evidence_maps_onto_ac_1_through_12():
    section = _evidence_section("KLC-105")
    ac_ids = [f"AC-{n}" for n in range(1, 13)]
    by_ac, _malformed = eg.parse_evidence(section, ac_ids)
    unmapped = [ac for ac in ac_ids if ac not in by_ac]
    assert not unmapped, f"KLC-105 Evidence left {unmapped} unmapped"


def test_klc103_build_log_evidence_parses_including_multi_id_heading():
    section = _evidence_section("KLC-103")
    ac_ids = [f"AC-{n}" for n in range(1, 13)]
    by_ac, _malformed = eg.parse_evidence(section, ac_ids)
    assert "AC-6" in by_ac and "AC-7" in by_ac
    assert by_ac["AC-6"] is by_ac["AC-7"], (
        "the '### AC-6 / AC-7' heading must yield ONE entry covering both ids")


def test_klc107_build_log_evidence_parses_from_paragraph_anchors():
    section = _evidence_section("KLC-107")
    ac_ids = [f"AC-{n}" for n in range(1, 31)]
    by_ac, _malformed = eg.parse_evidence(section, ac_ids)
    assert by_ac, "at least one well-formed entry must parse from paragraph anchors"
    for ac in ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6"):
        assert ac in by_ac, f"the AC-1..AC-6 range form must expand to include {ac}"


def test_klc107_build_log_ac21_ac23_map_to_genuine_evidence_not_the_full_suite_run():
    """review-fix (HIGH, AC-1/AC-17/AC-19): a mid-paragraph continuation line
    must never fork a competing anchor. KLC-107's real, unedited build-log.md
    has exactly this shape: '(AC-20, AC-22, AC-24 produce no finding at
    all... because no candidate test file names them anywhere; AC-21/AC-23
    surface because...' is ONE parenthetical whose second line is a
    grammatical continuation that happens to name AC-21/AC-23. Before the
    fix, that continuation line opened its own anchor and stole the
    textually-unrelated 'Full regression suite' pytest block as AC-21/AC-23's
    evidence. After the fix, AC-21/AC-23 must resolve to the earlier,
    GENUINE anchor — the one whose fenced block is the actual
    `ac_test_coverage.check()` run that literally prints 'AC-21 miss surface'
    / 'AC-23 miss surface'."""
    section = _evidence_section("KLC-107")
    ac_ids = [f"AC-{n}" for n in range(1, 31)]
    by_ac, _malformed = eg.parse_evidence(section, ac_ids)

    for ac in ("AC-21", "AC-23"):
        assert ac in by_ac, f"{ac} lost its entry entirely"
        entry = by_ac[ac]
        assert "ac_test_coverage" in " ".join(entry.commands), (
            f"{ac} must map to the ac_test_coverage run, got commands="
            f"{entry.commands!r}")
        assert "pytest tests/ --ignore=tests/fixtures" not in " ".join(entry.commands), (
            f"{ac} was misattributed to the unrelated full-suite pytest run")

    # Every genuine range-expanded/paragraph-anchored id from the earlier
    # AC-1..AC-6 rows must still be present — the fix must not regress the
    # existing coverage this test already pinned.
    for ac in ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6"):
        assert ac in by_ac, f"the AC-1..AC-6 range form must still expand to include {ac}"
