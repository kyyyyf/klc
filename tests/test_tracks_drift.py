import re
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.skills.track_classifier import final_track, TRACK_THRESHOLDS
from core.skills import gen_tracks_doc as G


def _track(total):
    """Call final_track with no upward-override axes and XS floor."""
    track, _ = final_track("XS", {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": total}, True)
    return track


def test_thresholds_single_source():
    assert (_track(2), _track(5), _track(8), _track(9)) == ("XS", "S", "M", "L")
    assert dict(TRACK_THRESHOLDS)["S"] == 5


def test_render_contains_thresholds_and_sequences():
    seqs = G.render_phase_sequences()
    assert "intake" in seqs and "discovery-lite" in seqs
    assert "build" in seqs and "review" in seqs
    table = G.render_thresholds_table()
    assert "XS" in table and "5" in table


def _strip_generated(s: str) -> str:
    return re.sub(
        r"<!-- BEGIN GENERATED:[^-]*-->.*?<!-- END GENERATED:[^-]*-->", "", s, flags=re.DOTALL
    )


def test_generation_preserves_prose():
    cur = G.DOC_PATH.read_text(encoding="utf-8")
    new = G.apply(cur)
    assert _strip_generated(cur) == _strip_generated(new)


def test_replace_region_append_when_markers_absent():
    """_replace_region must append block when neither marker exists yet."""
    doc = "# prose\nsome text\n"
    result = G._replace_region(doc, "x", "body content")
    assert "# prose" in result
    assert "<!-- BEGIN GENERATED:x -->" in result
    assert "body content" in result
    assert "<!-- END GENERATED:x -->" in result


def test_replace_region_raises_on_malformed():
    """_replace_region must raise ValueError when BEGIN present but END missing."""
    doc = "# prose\n<!-- BEGIN GENERATED:x -->\nstale body\n"
    with pytest.raises(ValueError, match="Malformed region"):
        G._replace_region(doc, "x", "new body")


def test_l_lower_bound_derived_from_thresholds():
    """L lower bound in table must be computed from M max, not hardcoded."""
    table = G.render_thresholds_table()
    # Find M's max from TRACK_THRESHOLDS
    m_max = dict(TRACK_THRESHOLDS)["M"]
    assert f"≥{m_max + 1}" in table, f"L row should show ≥{m_max + 1}, got: {table}"


def test_render_rows_present():
    """Threshold table must contain all four tracks with correct values."""
    table = G.render_thresholds_table()
    assert "| M | 8 |" in table
    assert "| S | 5 |" in table
    assert "| XS | 2 |" in table
    assert "| L | unbounded" in table


def test_committed_doc_matches_fresh_render():
    cur = G.DOC_PATH.read_text(encoding="utf-8")
    assert G.apply(cur) == cur, "run: python3 core/skills/gen_tracks_doc.py --write"
