"""KLC-103 — AC-4: the patterns added by this ticket capture no declaration
nested inside a function or method body, run against the REAL new TS/TSX/JS
rule files (not a mock)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "rules" / "typescript"

sys.path.insert(0, str(SKILLS))
import deterministic_inventory as di  # noqa: E402
import tools  # noqa: E402


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def test_ts_js_nested_function_body_locals_not_captured():
    """AC-4: the fixtures under tests/fixtures/rules/typescript/ each declare
    a `notExported()`/`Local()` function whose body contains a same-named
    local (`const local = 1` / `class LocalCls {}`). The emitted symbol set
    must equal exactly the enumerated TOP-LEVEL set — nothing from inside a
    function body leaks in."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(
        FIXTURES, ruleset, astgrep,
        files=["sample.ts", "sample.tsx", "sample.js"],
    )
    names = {s["name"] for s in inv["symbols"]}
    # None of the nested-local names appear anywhere in the merged output.
    assert "local" not in names
    assert "LocalCls" not in names
    assert "Local" not in names  # the .tsx fixture's nested function itself
    assert "notExported" not in names
    # And the top-level set is exactly what's expected (regression floor).
    expected = {
        "PLAIN", "TYPED", "fn", "generic", "Foo", "Baz", "IFoo", "Alias",
        "Color", "DefaultCls",              # sample.ts
        "Comp", "Button", "Widget", "export default React.memo",  # sample.tsx
        "Named", "Bar",                      # sample.js-only names
    }
    assert names == expected
