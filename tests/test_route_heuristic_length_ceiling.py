"""KLC-028 step-2: length feeds confidence only, not the track ceiling."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "skills"))
from route_heuristic import classify


def _long_text(words=350):
    return " ".join(["word"] * words)


def test_long_keyword_free_bug_not_raised():
    """Long (≥300 words), keyword-free, kind=bug → ≤S (length must not raise ceiling)."""
    result = classify(_long_text(350), kind="bug", modules=[])
    assert result.hint in ("XS", "S"), (
        f"Expected XS or S for long keyword-free bug, got {result.hint}"
    )


def test_long_text_xs_when_kind_bug_no_signal():
    """Even 400-word bug report with no keywords stays at S or below."""
    result = classify(_long_text(400), kind="bug", modules=[])
    assert result.hint in ("XS", "S")


def test_length_signal_still_recorded():
    """signals['length'] must still be present (telemetry preserved)."""
    result = classify(_long_text(350), kind="bug", modules=[])
    assert "length" in result.signals


def test_length_still_raises_confidence():
    """Word count ≥100 must produce confidence='high' regardless of track."""
    result = classify(_long_text(150), kind="bug", modules=[])
    assert result.confidence == "high"


def test_upward_aggregation_preserved():
    """M-keywords still raise hint to M even on short text."""
    text = "refactor architecture redesign entire system"
    result = classify(text, kind="unknown", modules=[])
    assert result.hint in ("M", "L")
