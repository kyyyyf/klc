"""KLC-108 — the C++ rule set (`core/rules/cpp/header-symbols.yaml`,
`virtual-methods.yaml`) captures only module-scope declarations and the class
members `virtual-methods.yaml` deliberately matches by design — never a
declaration nested inside a FREE function body (AC-3). The merged-ruleset
test below is `[!DECISION D-108-2]`, resolving impl-plan-review finding F-1
(medium): the same whole-profile merged-scan proof
`tests/test_rules_typescript.py::test_merged_ts_tsx_js_ruleset_scan_exits_zero`
gives for TypeScript, exercised here through real C++ source.

Real-substrate: the REAL rule files, through the REAL production scan path
(`deterministic_inventory.build_inventory`) — no ad-hoc sgconfig.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rules" / "cpp"

sys.path.insert(0, str(SKILLS))
import deterministic_inventory as di  # noqa: E402
import tools  # noqa: E402


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def _symbol_names(files: list[str]) -> dict[str, set[str]]:
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(FIXTURES, ruleset, astgrep, files=files)
    out: dict[str, set[str]] = {f: set() for f in files}
    for s in inv["symbols"]:
        if s["file"] in out:
            out[s["file"]].add(s["name"])
    return out


def test_cpp_function_body_locals_not_captured():
    """AC-3: `header-symbols.yaml`'s `class $NAME`/`struct $NAME` patterns
    must not match a local class/struct declared inside a free function's
    body."""
    names = _symbol_names(["scope.h"])["scope.h"]
    assert "LocalC" not in names and "LocalS" not in names, names


def test_cpp_module_scope_declaration_still_captured():
    """AC-5 regression guard: the fixture's own top-level class declaration
    still matches."""
    names = _symbol_names(["scope.h"])["scope.h"]
    assert "Widget" in names, names


def test_cpp_class_method_still_matched_by_virtual_methods_rule():
    """Edge case named in spec.md's Affected-modules section:
    `virtual-methods.yaml` matches class members by design via its
    `context` + `selector` pattern and must keep doing so after the sibling
    `header-symbols.yaml` gains the scope restriction — its OWN declared
    `valid` cases (none of which are inside a function body) must still all
    pass through the production executor."""
    _astgrep_or_skip()
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from rule_test_executor import run_rule_tests
    failures = run_rule_tests([REPO_ROOT / "core" / "rules" / "cpp"], {})
    valid_failures = [f for f in failures if "virtual-methods.yaml" in f and "[valid" in f]
    assert valid_failures == [], valid_failures


def test_merged_ruleset_scan_exits_zero_cpp_fixtures():
    """[!DECISION D-108-2] (impl-plan-review F-1, medium): the FULL merged
    ruleset must exit 0 and capture the expected symbols when scanning REAL
    C++ fixtures (a header AND a .cpp free-function/virtual-method file),
    not abort to the regex fallback."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(FIXTURES, ruleset, astgrep,
                             files=["scope.h", "scope.cpp"])
    assert inv["errors"] == [], f"merged scan degraded: {inv['errors']}"
    assert inv["source_of_truth"].get("cpp") == "ast_grep"
    by_file: dict[str, set[str]] = {}
    for s in inv["symbols"]:
        by_file.setdefault(s["file"], set()).add(s["name"])
    assert by_file.get("scope.h") == {"Widget"}
    # `header-symbols.yaml`'s `language: cpp` rule applies to `.cpp` files
    # too (`metadata.extensions` is documentation, not an ast-grep filter —
    # verified against the PRE-EXISTING `tests/fixtures/rules/coverage/
    # sample.cpp` fixture before this ticket's changes), so the top-level
    # `class Shape` is captured by header-symbols.yaml AND `Area` by
    # virtual-methods.yaml; the nested `LocalShape`/its `Area` must not be.
    assert by_file.get("scope.cpp") == {"Shape", "Area"}
