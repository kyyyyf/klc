"""KLC-108 — AC-4: the symbol inventory built over the klc repository
contains zero symbols of kind `variable` whose line falls inside a Python
function body.

Real-substrate: reads the live `.klc/index/inventory.json` (built by the
production `deterministic_inventory.py` over the actual repository, AFTER
step-1/step-2's rule changes), read-only — this step writes no production
code and rebuilds nothing itself.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests" / "shared"))

from inventory_scope import function_body_ranges, in_body_symbols  # noqa: E402

INDEX = REPO_ROOT / ".klc" / "index"


def _load_inventory() -> dict:
    p = INDEX / "inventory.json"
    if not p.exists():
        pytest.skip("no .klc/index/inventory.json — run the inventory builder first")
    return json.loads(p.read_text(encoding="utf-8"))


def test_zero_python_variable_symbols_inside_function_body():
    """AC-4: an automated assertion resolves each Python symbol's line
    against that file's parsed function-body ranges and reports 0, against
    the recorded baseline (F-001: 9 140 of 11 595 before this ticket's rule
    changes)."""
    inventory = _load_inventory()
    py_symbols = [s for s in inventory.get("symbols") or []
                 if (s.get("file") or "").endswith(".py")]
    violations = [s for s in in_body_symbols(inventory, REPO_ROOT)
                 if s.get("kind") == "variable"]
    assert violations == [], (
        f"{len(violations)} of {len(py_symbols)} Python symbols resolve "
        f"inside a function body (baseline before this ticket: 9 140 of "
        f"11 595) — first few: {violations[:5]}")


def test_scope_assertion_flags_a_planted_in_body_variable(tmp_path):
    """Fail-closed twin: a synthetic inventory record naming a `kind:
    variable` symbol with a line number inside a fixture's function-body
    range must be reported, not silently passed as 0."""
    source = "def run():\n    out = 1\n    return out\n"
    ranges = function_body_ranges(source)
    assert ranges == [(2, 3)], ranges

    (tmp_path / "planted.py").write_text(source, encoding="utf-8")
    inv = {"symbols": [
        {"name": "out", "kind": "variable", "file": "planted.py", "line": 2},
        {"name": "run", "kind": "function", "file": "planted.py", "line": 1},
    ]}
    flagged = in_body_symbols(inv, tmp_path)
    assert [f["name"] for f in flagged] == ["out"]
