#!/usr/bin/env python3
"""KLC-107 step-12 — AC-30 meta-test: the suite covers the four behaviours
this ticket SHIPS, and the fifth (deferred to KLC-121 by [!DECISION D-001])
is deliberately absent, finding-F-4 fix per [!DECISION D-204]."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"

_NODE_RE = re.compile(r"::(test_\w+)")


def _collect_test_node_names(path: Path) -> set[str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(path)],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,
    )
    return {m.group(1) for m in _NODE_RE.finditer(r.stdout)}


def test_suite_covers_the_four_shipped_behaviours_and_defers_the_fifth():
    """AC-30 names five behaviours. Four ship on KLC-107; the fifth
    (test_incremental_output_matches_full_rebuild, AC-22) is deferred with
    AC-20..AC-24 by [!DECISION D-001] to follow-up ticket KLC-121, which owns
    tests/integration/test_klc107_incremental.py. When KLC-121 lands, delete
    the absence block below and move the fifth name into SHIPPED — that
    restores the strict five-of-five check in one edit."""
    SHIPPED = (
        "test_index_freshness_fails_when_last_run_behind_head",
        "test_intake_refreshes_index_before_writing_ticket_artifact",
        "test_stale_modules_contains_only_directly_touched_module",
        "test_install_prints_snippet_and_leaves_manager_files_untouched",
    )
    DEFERRED_TO_KLC121 = "test_incremental_output_matches_full_rebuild"

    collected = _collect_test_node_names(TESTS / "integration")
    for name in SHIPPED:
        assert name in collected, f"AC-30 behaviour not collected: {name}"

    assert DEFERRED_TO_KLC121 not in collected
    assert not (TESTS / "integration" / "test_klc107_incremental.py").exists()


if __name__ == "__main__":
    import unittest
    unittest.main()
