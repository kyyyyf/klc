"""KLC-028 step-1: track_classifier pure module — symmetric downgrade gate."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core" / "skills"))

import track_classifier as _tc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _modules_index(entries):
    return {"modules": entries}


def _mod(name, path, depended_by):
    return {"name": name, "path": path, "depended_by": depended_by, "depends_on": []}


def _estimate(complexity=1, uncertainty=1, risk=1, manual=0, total=None):
    t = total if total is not None else complexity + uncertainty + risk + manual
    return {"complexity": complexity, "uncertainty": uncertainty,
            "risk": risk, "manual": manual, "total": t}


# ---------------------------------------------------------------------------
# is_downgrade_safe
# ---------------------------------------------------------------------------

def test_downgrade_allowed_low_blast_radius():
    """All affected modules have depended_by known and external fan-in = 0."""
    idx = _modules_index([
        _mod("modA", "src/a", []),
        _mod("modB", "src/b", []),
    ])
    safe, info = _tc.is_downgrade_safe(["modA", "modB"], idx)
    assert safe is True
    assert info["external_dependents"] == []


def test_hold_floor_when_blast_radius_unavailable():
    """Module present but depended_by key absent → not safe (hold floor)."""
    idx = _modules_index([
        {"name": "modA", "path": "src/a", "depends_on": []},  # no depended_by
    ])
    safe, info = _tc.is_downgrade_safe(["modA"], idx)
    assert safe is False
    assert "depended_by" in info.get("reason", "")


def test_stub_graph_holds_floor():
    """Empty modules index → not safe (no evidence)."""
    safe, info = _tc.is_downgrade_safe(["modA"], _modules_index([]))
    assert safe is False


def test_affected_module_missing_holds_floor():
    """Affected module not found in index → not safe."""
    idx = _modules_index([_mod("modB", "src/b", [])])
    safe, info = _tc.is_downgrade_safe(["modA"], idx)
    assert safe is False


def test_external_dependent_blocks_downgrade():
    """modC depends on modA and is not in affected set → not safe."""
    idx = _modules_index([
        _mod("modA", "src/a", ["modC"]),
        _mod("modB", "src/b", []),
        _mod("modC", "src/c", []),
    ])
    safe, info = _tc.is_downgrade_safe(["modA", "modB"], idx)
    assert safe is False
    assert "modC" in info["external_dependents"]


def test_internal_dependent_ok():
    """Both modules in the affected set depending on each other is safe."""
    idx = _modules_index([
        _mod("modA", "src/a", ["modB"]),
        _mod("modB", "src/b", ["modA"]),
    ])
    safe, info = _tc.is_downgrade_safe(["modA", "modB"], idx)
    assert safe is True


def test_empty_affected_set_holds_floor():
    """No affected modules = absence of evidence → not safe (hold floor)."""
    idx = _modules_index([_mod("modA", "src/a", [])])
    safe, info = _tc.is_downgrade_safe([], idx)
    assert safe is False
    assert "blast" in info["reason"].lower() or "no affected" in info["reason"].lower()


# ---------------------------------------------------------------------------
# final_track
# ---------------------------------------------------------------------------

def test_final_track_no_downgrade_when_not_safe():
    """floor=M, estimate says S, but not safe → holds M."""
    est = _estimate(1, 1, 1, 0, total=3)
    track, reason = _tc.final_track("M", est, downgrade_safe=False)
    assert track == "M"


def test_final_track_downgrade_when_safe():
    """floor=M, estimate says S, safe → S."""
    est = _estimate(1, 1, 1, 0, total=3)
    track, reason = _tc.final_track("M", est, downgrade_safe=True)
    assert track == "S"


def test_axis3_floors_at_m():
    """Any axis = 3 → floor at M even if estimate total is low."""
    est = _estimate(complexity=3, uncertainty=1, risk=1, manual=0, total=5)
    track, reason = _tc.final_track("S", est, downgrade_safe=True)
    assert track == "M"


def test_uncertainty3_total7_forces_l():
    """uncertainty=3 and total≥7 → L."""
    est = _estimate(complexity=2, uncertainty=3, risk=1, manual=1, total=7)
    track, reason = _tc.final_track("S", est, downgrade_safe=True)
    assert track == "L"


def test_upward_override_preserved():
    """floor=M, estimate total=10 → L (upward from floor)."""
    est = _estimate(complexity=3, uncertainty=3, risk=3, manual=1, total=10)
    track, reason = _tc.final_track("M", est, downgrade_safe=False)
    assert track == "L"
