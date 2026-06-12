"""Tests for intake B+A routing decision wiring (change 1).

Run with pytest, or standalone: `python3 tests/test_intake_routing.py`.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core" / "phases"))
import intake  # noqa: E402


def test_short_ambiguous_recommends_triage():
    r = intake._classify_route("make it better", "tech")
    assert r["confidence"] == "low"
    assert r["decision"] == "triage"


def test_confident_complex_is_trusted():
    r = intake._classify_route("add an auth migration to the schema", "feature")
    assert r["hint"] == "M"
    assert r["decision"] == "trust"


def test_triage_disabled_low_confidence_goes_full_discovery():
    os.environ["KLC_INTAKE_TRIAGE"] = "0"
    try:
        assert intake._triage_available() is False
        r = intake._classify_route("make it better", "tech")
        assert r["decision"] == "full-discovery"
    finally:
        os.environ.pop("KLC_INTAKE_TRIAGE", None)


def test_classify_route_never_raises_shape():
    r = intake._classify_route("", "unknown")
    assert set(r) == {"hint", "signals", "confidence", "mentions", "decision"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
