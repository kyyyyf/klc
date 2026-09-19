"""KLC-106 step-4 — the inventory and callgraph builders record the same
verdict (AC-7).

The inventory records one verdict PER LANGUAGE (files-with-symbols over that
language's file count, D-005); each callgraph builder records one verdict
(callgraph symbols over inventory symbols for its language). Both fail
closed when the denominator is missing or zero — never a ZeroDivisionError,
never a fabricated healthy ratio.
"""
from __future__ import annotations

import sys
from pathlib import Path

_skills = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
if str(_skills) not in sys.path:
    sys.path.insert(0, str(_skills))

import deterministic_inventory as di  # noqa: E402
import callgraph_python as cg_py  # noqa: E402


def test_inventory_and_callgraph_builders_record_verdict_below_threshold():
    structural = {"languages": {"python": {"files": 20}, "typescript": {"files": 5}}}
    symbols = [
        {"name": "f", "kind": "function", "file": "a.py", "line": 1,
         "signature": "f()", "visibility": "public", "source_of_truth": "regex",
         "lang": "python", "rule": "regex-fallback"},
    ]
    verdicts = di.inventory_coverage_verdicts(symbols, structural)
    by_lang = {v["builder"]: v for v in verdicts}
    py_verdict = by_lang["inventory:python"]
    assert py_verdict["degraded"] is True
    assert py_verdict["observed"] == 1
    assert py_verdict["universe"] == 20

    inventory = {"symbols": symbols}
    cg_symbols = {}  # zero callgraph symbols produced
    v = cg_py.coverage_verdict(cg_symbols, inventory)
    assert v["builder"] == "callgraph:python"
    assert v["degraded"] is True
    assert v["observed"] == 0
    assert v["universe"] == 1


def test_callgraph_builder_with_zero_inventory_symbols_denominator_degrades_not_divides_by_zero():
    inventory = {"symbols": []}
    v = cg_py.coverage_verdict({"a.py::f": object()}, inventory)
    assert v["degraded"] is True
    assert v["universe"] == 0
    assert "ZeroDivisionError" not in v["reason"]

    v_absent = cg_py.coverage_verdict({}, None)
    assert v_absent["degraded"] is True
