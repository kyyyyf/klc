#!/usr/bin/env python3
"""timing_report.py — AC-5's "both medians in the build log" contract (KLC-121).

`median_delta_report()` turns two lists of run durations (pre-change,
post-change) into three log lines carrying both medians and the delta.
This module proves the LOGGING CONTRACT only: it does not itself measure
anything, and it does not prove the speed-up — that is a same-session,
scratch-clone, ten-run manual procedure (test-plan.md's AC-5 manual
checklist, run once by the build agent and recorded in `build-log.md`).
"""
from __future__ import annotations

import statistics


def median_delta_report(pre_s: list[float], post_s: list[float]) -> str:
    """Three lines: the pre-change median over N runs, the post-change
    median over M runs, and the signed delta pre-minus-post (positive
    means the post-change run got faster). Raises `statistics.StatisticsError`
    on an empty list — a caller with no samples has nothing to report and
    should not silently print a bogus median."""
    pre_m = statistics.median(pre_s)
    post_m = statistics.median(post_s)
    return (
        f"[timing] pre-change median {pre_m:.3f}s over {len(pre_s)} runs\n"
        f"[timing] post-change median {post_m:.3f}s over {len(post_s)} runs\n"
        f"[timing] delta {pre_m - post_m:+.3f}s"
    )
