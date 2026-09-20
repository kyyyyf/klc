#!/usr/bin/env python3
"""KLC-107 step-12 — AC-30 meta-test, then KLC-121 step-6's AC-10
bookkeeping close-out.

The original single function (`test_suite_covers_the_four_shipped_behaviours_and_defers_the_fifth`)
asserted that KLC-107's own four shipped behaviours were collected, that
the fifth (deferred to KLC-121 by [!DECISION D-001]) was NOT collected, and
that `tests/integration/test_klc107_incremental.py` did not yet exist.
KLC-121 ships three of D-001's five deferred behaviours (AC-20/23/24) in
that exact file, so that function is replaced by the two below (AC-10;
finding F-4's fix, [!DECISION D-204], carried the file-absence half of the
old function until KLC-121 step-2 deleted it — see git history)."""
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


def test_klc121_incremental_bookkeeping_replaces_the_file_absence_check():
    """AC-10: `tests/integration/test_klc107_incremental.py` collects the
    three behaviours KLC-121 shipped from KLC-107's D-001 deferral
    (AC-20/23/24), and the fifth deferred name
    (`test_incremental_output_matches_full_rebuild`, AC-22, which travels
    to KLC-125 along with the merge it tests) is still not collected
    anywhere — its explanatory comment in `test_klc107_incremental.py`'s
    own docstring now names KLC-125, not KLC-121."""
    SHIPPED_BY_KLC121 = (
        "test_structural_json_carries_stable_per_file_fingerprint",
        "test_profile_resolved_exactly_once_per_run",
        "test_incremental_falls_back_to_full_rebuild_and_says_so",
    )
    DEFERRED_TO_KLC125 = "test_incremental_output_matches_full_rebuild"

    collected_incremental = _collect_test_node_names(
        TESTS / "integration" / "test_klc107_incremental.py")
    for name in SHIPPED_BY_KLC121:
        assert name in collected_incremental, f"KLC-107 AC-20/23/24 not collected: {name}"

    assert DEFERRED_TO_KLC125 not in _collect_test_node_names(TESTS / "integration")

    incremental_source = (
        TESTS / "integration" / "test_klc107_incremental.py"
    ).read_text(encoding="utf-8")
    assert "KLC-125" in incremental_source, (
        "test_klc107_incremental.py's deferral comment must name KLC-125, "
        "not KLC-121, as the ticket that will ship the fifth behaviour")


def test_klc107_ac30_four_shipped_behaviours_stay_collected_alongside_klc121s_three():
    """AC-10: KLC-107's AC-30 collection guarantee is carried forward, not narrowed —
    the four behaviours KLC-107 itself shipped are still collected in
    `tests/integration`, together with the three KLC-121 shipped from D-001's
    deferral, and the fifth deferred name stays absent until KLC-125 (review
    round-1 fix: the replacement of the original meta-test had dropped the four
    original names)."""
    SHIPPED_BY_KLC107 = (
        "test_index_freshness_fails_when_last_run_behind_head",
        "test_intake_refreshes_index_before_writing_ticket_artifact",
        "test_stale_modules_contains_only_directly_touched_module",
        "test_install_prints_snippet_and_leaves_manager_files_untouched",
    )
    SHIPPED_BY_KLC121 = (
        "test_structural_json_carries_stable_per_file_fingerprint",
        "test_profile_resolved_exactly_once_per_run",
        "test_incremental_falls_back_to_full_rebuild_and_says_so",
    )
    DEFERRED_TO_KLC125 = "test_incremental_output_matches_full_rebuild"

    collected = _collect_test_node_names(TESTS / "integration")
    for name in SHIPPED_BY_KLC107 + SHIPPED_BY_KLC121:
        assert name in collected, f"AC-30 behaviour not collected: {name}"
    assert DEFERRED_TO_KLC125 not in collected


def test_klc107_test_plan_rows_repoint_ac20_23_24_to_shipped_tests_and_ac21_22_to_klc125():
    """AC-10: Text-based check over `.klc/tickets/KLC-107/test-plan.md`: the
    AC-20, AC-23 and AC-24 rows name the three tests KLC-121 shipped (no
    longer `—`/"deferred to KLC-121"), and the AC-21 and AC-22 rows now say
    "deferred to KLC-125" rather than "deferred to KLC-121". `.klc/` is
    git-ignored on `main` and the ticket tree lives on the `klc-state`
    branch (KLC-115's degrade pattern, `test_klc115_fact_source.py:125-126`),
    so this test SKIPS rather than fails on a checkout without it — a hard
    failure on a clean clone would be a false red."""
    test_plan = REPO / ".klc" / "tickets" / "KLC-107" / "test-plan.md"
    if not test_plan.exists():
        import pytest
        pytest.skip("KLC-107 ticket tree not present on this checkout "
                    "(lives on the klc-state branch)")

    text = test_plan.read_text(encoding="utf-8")
    lines = {}
    for line in text.splitlines():
        for ac in ("AC-20", "AC-21", "AC-22", "AC-23", "AC-24"):
            if line.startswith(f"| {ac} "):
                lines[ac] = line

    shipped = {
        "AC-20": "test_structural_json_carries_stable_per_file_fingerprint",
        "AC-23": "test_profile_resolved_exactly_once_per_run",
        "AC-24": "test_incremental_falls_back_to_full_rebuild_and_says_so",
    }
    for ac, test_name in shipped.items():
        assert ac in lines, f"{ac} row missing from KLC-107 test-plan.md"
        assert test_name in lines[ac], f"{ac} row does not name {test_name}: {lines[ac]}"
        assert "deferred to KLC-121" not in lines[ac], lines[ac]

    for ac in ("AC-21", "AC-22"):
        assert ac in lines, f"{ac} row missing from KLC-107 test-plan.md"
        assert "deferred to KLC-125" in lines[ac], lines[ac]
        assert "deferred to KLC-121" not in lines[ac], lines[ac]


if __name__ == "__main__":
    import unittest
    unittest.main()
