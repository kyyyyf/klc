"""KLC-139 step-1: the shared ast-grep range helper `match_line_range`.

`deterministic_inventory.match_line_range` is the single conversion of an
ast-grep match's 0-based `range` into 1-based inclusive `(start, end)` lines
(KLC-137 D-101, adopted by KLC-139 D-203). Both tests are cited under the
test-plan's AC-6 rows.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core" / "skills"))

import deterministic_inventory as di  # noqa: E402


def test_match_line_range_converts_zero_based_to_one_based_inclusive():
    """AC-6: a real ast-grep match's 0-based range becomes 1-based inclusive."""
    # F-008 shape: `export function ok()` matched lines 0-2 (0-based), so the
    # 1-based inclusive range is (1, 3).
    match = {
        "text": "export function ok() {\n  return 1;\n}",
        "range": {"start": {"line": 0, "column": 0}, "end": {"line": 2, "column": 1}},
    }
    assert di.match_line_range(match) == (1, 3)

    one_line = {"range": {"start": {"line": 4, "column": 0}, "end": {"line": 4, "column": 10}}}
    assert di.match_line_range(one_line) == (5, 5)


def test_match_line_range_returns_none_for_unusable_or_inverted_ranges():
    """AC-6: a missing, malformed or inverted range yields None, never a guess."""
    assert di.match_line_range({}) is None
    assert di.match_line_range({"range": {"start": {"line": 0}}}) is None
    assert di.match_line_range(
        {"range": {"start": {"line": "0"}, "end": {"line": 2}}}
    ) is None
    assert di.match_line_range(
        {"range": {"start": {"line": True}, "end": {"line": 2}}}
    ) is None
    assert di.match_line_range(
        {"range": {"start": {"line": -1}, "end": {"line": 2}}}
    ) is None
    assert di.match_line_range(
        {"range": {"start": {"line": 4}, "end": {"line": 1}}}
    ) is None
