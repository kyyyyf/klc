"""KLC-137 step-2 — the regex fallback records `line_end: null` (AC-2).

The regex path has no end position at all, so every regex-produced symbol
must carry `line_end` as JSON `null` (present, not absent) — no consumer may
mistake a one-line regex match for a real ast-grep range.
"""
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(SKILLS))

from core.shared.inventory import SYMBOL_FIELDS, symbol_range  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc137_fixtures import real_inventory, write_python_fixture  # noqa: E402

pytestmark = pytest.mark.usefixtures("hermetic_project_root")


def test_regex_fallback_symbol_key_set_equals_frozen_fields_with_line_end_null(tmp_path):
    """AC-2: every regex-produced symbol's key set equals `SYMBOL_FIELDS`
    exactly (line_end included), and its value is JSON `null`."""
    root = tmp_path / "proj"
    write_python_fixture(root)
    inv = real_inventory(root, astgrep=False)
    assert inv["symbols"], "fixture must yield at least one regex symbol"
    for s in inv["symbols"]:
        assert s["source_of_truth"] == "regex"
        assert set(s) == set(SYMBOL_FIELDS)
        assert "line_end" in s
        assert s["line_end"] is None


def test_symbol_range_returns_none_for_every_regex_produced_symbol(tmp_path):
    """AC-2: the public entry point (`symbol_range`), not the private regex
    internals — every regex-sourced symbol returns `None`, so no consumer
    mistakes a one-line regex match for a real range. First asserts every
    symbol really carries `line_end: null` (not merely absent), so this test
    cannot pass vacuously on a symbol that simply lacks the key."""
    root = tmp_path / "proj"
    write_python_fixture(root)
    inv = real_inventory(root, astgrep=False)
    assert inv["symbols"], "fixture must yield at least one regex symbol"
    for s in inv["symbols"]:
        assert "line_end" in s and s["line_end"] is None
        assert symbol_range(s) is None
