#!/usr/bin/env python3
"""KLC-121 step-2 — AC-5's LOGGING CONTRACT.

`timing_report.median_delta_report()` turns two lists of stubbed run
durations into the exact three-line form the build log must carry. This
test proves the logging contract only — never the real speed-up. The real
same-session, scratch-clone, ten-run measurement is a manual procedure
(test-plan.md's AC-5 manual checklist), run once by the build agent and
recorded verbatim in build-log.md under "AC-5 same-session timing
measurement"; this test's own `## Evidence` entry cites THIS command, never
the timing procedure itself (design D-202: `klc ack` re-executes every
Evidence command under a budget, and a ten-run clone-and-measure loop would
either overrun it or run against the live working tree)."""
from __future__ import annotations

import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))

import timing_report  # noqa: E402


def test_build_log_records_both_medians_and_the_delta():
    """AC-5: the build log entry must carry BOTH medians and the computed
    delta — "a build that records only the delta or only one median does
    not satisfy AC-5" (test-plan.md). Five stubbed pre-change and five
    stubbed post-change durations, chosen so the medians are unambiguous."""
    pre = [1.88, 1.79, 1.87, 1.88, 1.80]
    post = [1.42, 1.40, 1.41, 1.43, 1.39]

    report = timing_report.median_delta_report(pre, post)

    assert "pre-change median 1.870s over 5 runs" in report
    assert "post-change median 1.410s over 5 runs" in report
    assert "delta +0.460s" in report


if __name__ == "__main__":
    import unittest
    unittest.main()
