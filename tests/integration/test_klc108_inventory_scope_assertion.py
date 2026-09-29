"""KLC-108 — AC-4: the symbol inventory built over the klc repository
contains zero symbols of kind `variable` whose line falls inside a Python
function body.

Real-substrate, hermetic (KLC-136 AC-1): the inventory is built from the
CURRENT tree (`fresh_index.build_fresh_inventory`), never read from
`.klc/index/inventory.json` — so the verdict is identical whether the live
index is absent, stale or current (`live_index_state`, parametrized), and
`no_index_reads()` proves it never even looked.
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests" / "shared"))

from inventory_scope import function_body_ranges, in_body_symbols  # noqa: E402
import fresh_index as fresh_index_mod  # noqa: E402


@functools.lru_cache(maxsize=1)
def _fresh_inventory() -> dict:
    """Built once per test process (module-scoped cache): the three
    `live_index_state` parametrisations must not each pay for a fresh
    inventory build — the whole point of AC-1 is that the live index's
    state is irrelevant to this inventory's computation in the first
    place."""
    return fresh_index_mod.build_fresh_inventory(REPO_ROOT)


def _plantable_function(inventory: dict) -> tuple[dict, int]:
    """The first Python function symbol whose body (per `ast`, the same
    oracle `in_body_symbols` uses) actually contains the line right after
    its own `def` — so planting a violation there is guaranteed to land
    inside a real function body, not merely adjacent to one (e.g. a
    one-line stub)."""
    cache: dict[str, list[tuple[int, int]]] = {}
    for sym in inventory.get("symbols") or []:
        if sym.get("kind") != "function":
            continue
        f = sym.get("file") or ""
        if not f.endswith(".py") or not isinstance(sym.get("line"), int):
            continue
        if f not in cache:
            try:
                cache[f] = function_body_ranges(
                    (REPO_ROOT / f).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                cache[f] = []
        candidate_line = sym["line"] + 1
        if any(lo <= candidate_line <= hi for lo, hi in cache[f]):
            return sym, candidate_line
    raise AssertionError("no plantable function found in the fresh inventory")


@pytest.mark.parametrize("live_index_state", ["absent", "stale", "current"], indirect=True)
def test_zero_python_variable_symbols_inside_function_body(live_index_state, no_index_reads):
    """AC-1: an automated assertion resolves each Python symbol's line
    against that file's parsed function-body ranges and reports 0 — built
    from the current tree, so the live index's state (absent, stale by
    shifted line numbers, or current) never changes the verdict, and the
    check never even reads `.klc/index/` to get there."""
    inventory = _fresh_inventory()
    py_symbols = [s for s in inventory.get("symbols") or []
                 if (s.get("file") or "").endswith(".py")]
    violations = [s for s in in_body_symbols(inventory, REPO_ROOT)
                 if s.get("kind") == "variable"]
    assert violations == [], (
        f"{len(violations)} of {len(py_symbols)} Python symbols resolve "
        f"inside a function body — first few: {violations[:5]}")
    assert no_index_reads() == []


def test_planted_violation_still_fails_closed():
    """AC-1 NEGATIVE/gate-like twin: the fresh inventory plus one planted
    `kind: variable` record at the line after the `def` of a real function
    in it must be flagged, and ONLY that record — proves the tmp-built
    rewrite did not turn the check into an always-pass."""
    inventory = _fresh_inventory()
    fn, planted_line = _plantable_function(inventory)
    planted = {"name": "__klc136_planted__", "kind": "variable",
              "file": fn["file"], "line": planted_line}
    augmented = dict(inventory)
    augmented["symbols"] = list(inventory.get("symbols") or []) + [planted]
    flagged = [s for s in in_body_symbols(augmented, REPO_ROOT)
              if s.get("kind") == "variable"]
    assert flagged == [planted], flagged


def test_scope_assertion_flags_a_planted_in_body_variable(tmp_path):
    """AC-1: fail-closed twin (isolated fixture, not the repo tree) — a
    synthetic inventory record naming a `kind: variable` symbol with a line
    number inside a fixture's function-body range must be reported, not
    silently passed as 0."""
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
