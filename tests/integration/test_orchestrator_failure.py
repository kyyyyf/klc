"""KLC-052 step-7: run_signal.should_retry — AC-6 retry-once-then-stop.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import run_signal  # noqa: E402


def test_retries_once_on_bad_signal():
    # First failure on this phase -> retry the same phase once.
    assert run_signal.should_retry(1) is True


def test_stops_after_two_consecutive_failures():
    # Second consecutive failure -> stop, never a third dispatch.
    assert run_signal.should_retry(2) is False


def test_bad_signal_combined_with_retry_policy():
    # An unparseable signal (None) is exactly the trigger for the
    # retry decision — wire the two seams together as the loop would.
    unparseable = run_signal.parse_signal("no json here", expected_phase="design")
    assert unparseable is None
    failure_count = 1
    assert run_signal.should_retry(failure_count) is True
    failure_count += 1
    assert run_signal.should_retry(failure_count) is False
