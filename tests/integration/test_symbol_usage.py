"""KLC-071 step-6 — symbol_usage.json derived impact-radius view."""
import json
import sys
import tempfile
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import symbol_usage as su  # noqa: E402

_MODULES = {"modules": [
    {"name": "intake", "path": "core/intake"},
    {"name": "routing", "path": "core/routing"},
]}

_INVENTORY = {"symbols": [
    {"name": "validate_ticket", "kind": "function",
     "file": "core/intake/validation.py", "line": 1,
     "signature": "def validate_ticket(", "visibility": "public",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
    {"name": "_helper", "kind": "function", "file": "core/intake/validation.py",
     "line": 9, "signature": "def _helper(", "visibility": "private",
     "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
]}

# routing/router.py and a test both call validate_ticket.
_CALLGRAPH = {"symbols": {
    "core/intake/validation.py::validate_ticket": {
        "kind": "function", "file": "core/intake/validation.py",
        "called_by": ["core/routing/router.py::route",
                      "tests/test_validation.py::test_validate"]},
}}

_DEPGRAPH = {"import_graphs": {"python": {
    "nodes": [{"id": "core/intake/validation.py"}, {"id": "core/routing/router.py"},
              {"id": "tests/test_validation.py"}],
    "edges": [
        {"from": "core/routing/router.py", "to": "core/intake/validation.py"},
        {"from": "tests/test_validation.py", "to": "core/intake/validation.py"},
    ],
}}}


def test_callgraph_symbol_level_used_by():
    """AC-3: with a callgraph, used_by is symbol-level with the caller's module."""
    r = su.build_symbol_usage(_INVENTORY, _MODULES, _CALLGRAPH, None)
    key = "core/intake/validation.py::validate_ticket"
    sym = r["symbols"][key]
    assert sym["defined_in"] == "core/intake/validation.py"
    assert sym["module_name"] == "intake"
    assert sym["visibility"] == "public"
    users = {u["file"]: u for u in sym["used_by"]}
    assert "core/routing/router.py" in users
    assert users["core/routing/router.py"]["usage_type"] == "call"
    assert users["core/routing/router.py"]["module_name"] == "routing"
    # the test caller is surfaced as tested_by, not as a plain consumer.
    assert "tests/test_validation.py" in sym["tested_by"]


def test_degrade_without_callgraph_file_level():
    """AC-3: no callgraph → file-level usage from the import graph, confidence low,
    and the view never disappears."""
    r = su.build_symbol_usage(_INVENTORY, _MODULES, None, _DEPGRAPH)
    key = "core/intake/validation.py::validate_ticket"
    sym = r["symbols"][key]
    assert sym["used_by"]  # still present
    users = {u["file"]: u for u in sym["used_by"]}
    assert users["core/routing/router.py"]["usage_type"] == "import"
    assert users["core/routing/router.py"]["confidence"] == "low"
    assert "tests/test_validation.py" in sym["tested_by"]
    assert any("callgraph absent" in n for n in r["notes"])


def test_change_risk_scales_with_usage():
    """AC-3: change_risk is deterministic from visibility + fan-out."""
    r = su.build_symbol_usage(_INVENTORY, _MODULES, _CALLGRAPH, None)
    pub = r["symbols"]["core/intake/validation.py::validate_ticket"]
    priv = r["symbols"]["core/intake/validation.py::_helper"]
    assert pub["change_risk"] in {"low", "medium", "high"}
    # the unused private helper is the lowest risk.
    assert priv["change_risk"] == "low"
    assert priv["used_by"] == []


def test_multilang_callgraph_merge():
    """AC-3: all per-language callgraph files are merged (KLC-070 loader pattern)."""
    inv = {"symbols": [
        {"name": "do", "kind": "function", "file": "cg/target.cpp", "line": 1,
         "signature": "void do()", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "cpp", "rule": "cpp-public-api"}]}
    modules = {"modules": [{"name": "cg", "path": "cg"}]}
    rust_cg = {"symbols": {"cg/target.cpp::do": {
        "file": "cg/target.cpp", "called_by": ["cg/other.cpp::use"]}}}
    with tempfile.TemporaryDirectory() as d:
        cg_dir = Path(d) / "callgraph"
        cg_dir.mkdir()
        (cg_dir / "cpp.json").write_text(json.dumps(rust_cg), encoding="utf-8")
        merged = su.load_callgraph_dir(cg_dir)
    r = su.build_symbol_usage(inv, modules, merged, None)
    sym = r["symbols"]["cg/target.cpp::do"]
    assert any(u["file"] == "cg/other.cpp" for u in sym["used_by"])


def test_qualified_method_callers_found():
    """FIX-1: a callgraph key for a qualified method (`a.py::Class.method`, C++
    `a.cpp::Class::method`) must still match the UNQUALIFIED inventory symbol
    (`method`); otherwise public-method changes wrongly show used_by:[] / risk low."""
    inv = {"symbols": [
        {"name": "method", "kind": "method", "file": "a.py", "line": 1,
         "signature": "def method(self)", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "python", "rule": "py-public-api"},
        {"name": "run", "kind": "method", "file": "a.cpp", "line": 1,
         "signature": "void run()", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "cpp", "rule": "cpp-public-api"},
    ]}
    modules = {"modules": [{"name": "m", "path": "a.py"}, {"name": "c", "path": "a.cpp"}]}
    cg = {"symbols": {
        "a.py::Class.method": {"file": "a.py",
                               "called_by": ["b.py::x", "c.py::y", "d.py::z"]},
        "a.cpp::Ns::Class::run": {"file": "a.cpp", "called_by": ["e.cpp::u"]},
    }}
    r = su.build_symbol_usage(inv, modules, cg, None)
    py = r["symbols"]["a.py::method"]
    assert {u["file"] for u in py["used_by"]} == {"b.py", "c.py", "d.py"}
    assert py["change_risk"] == "high"          # fan-out of 3, not dropped to low
    cpp = r["symbols"]["a.cpp::run"]
    assert {u["file"] for u in cpp["used_by"]} == {"e.cpp"}


def test_cli_exit_2_without_inventory(tmp_path):
    """AC-2-style: fail-closed exit 2 when required inventory.json is absent."""
    rc = su.main(["--in-inventory", str(tmp_path / "nope.json"),
                  "--out", str(tmp_path / "usage.json")])
    assert rc == 2


def test_determinism():
    """AC-8: byte-identical on re-run; no inner timestamp."""
    a = su.build_symbol_usage(_INVENTORY, _MODULES, _CALLGRAPH, None)
    b = su.build_symbol_usage(_INVENTORY, _MODULES, _CALLGRAPH, None)
    assert json.dumps(a) == json.dumps(b)
    assert "generated_at" not in a
