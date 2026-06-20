import sys
from pathlib import Path
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


def test_generation_preserves_prose():
    import re
    cur = G.DOC_PATH.read_text(encoding="utf-8")
    new = G.apply(cur)
    strip = lambda s: re.sub(
        r"<!-- BEGIN GENERATED:.*?<!-- END GENERATED:[^>]*-->", "", s, flags=re.DOTALL
    )
    assert strip(cur) == strip(new)


def test_committed_doc_matches_fresh_render():
    cur = G.DOC_PATH.read_text(encoding="utf-8")
    assert G.apply(cur) == cur, "run: python3 core/skills/gen_tracks_doc.py --write"
