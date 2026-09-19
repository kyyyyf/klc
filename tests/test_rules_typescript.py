"""KLC-103 — AC-2 / AC-1 / F-1: the TypeScript-family rule set (`.ts`, `.tsx`,
`.js`) captures the annotated declaration forms, and the merged production
ruleset (all three sibling files loaded together) still parses and scans
cleanly.

Real-substrate tests: the REAL rule files, through the REAL production scan
path (`deterministic_inventory.build_inventory`, the same function
`klc init` calls) — no ad-hoc sgconfig, no mocked ast-grep output.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rules" / "typescript"

sys.path.insert(0, str(SKILLS))
import deterministic_inventory as di  # noqa: E402
import tools  # noqa: E402


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def _symbol_names(files: list[str]) -> dict[str, set[str]]:
    """Run the REAL merged ruleset (active profile) over `files` under the
    fixture dir, through the production build_inventory() path. Returns
    {file: {names}}."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(FIXTURES, ruleset, astgrep, files=files)
    out: dict[str, set[str]] = {f: set() for f in files}
    for s in inv["symbols"]:
        if s["file"] in out:
            out[s["file"]].add(s["name"])
    return out


def test_ts_declaration_forms_exact_symbol_set():
    """AC-2: the plain, type-annotated, return-type-annotated, generic,
    `extends`, `abstract` and default-export forms — one exact set, no
    under- or over-capture (nested locals in the fixture must not appear)."""
    names = _symbol_names(["sample.ts"])["sample.ts"]
    assert names == {
        "PLAIN", "TYPED", "fn", "generic", "Foo", "Baz", "IFoo", "Alias",
        "Color", "DefaultCls",
    }


def test_tsx_declaration_forms_exact_symbol_set():
    """AC-2, `.tsx` — the row that proves the `.tsx` blind spot (spec.md
    Defect 1) is closed: a `language: typescript` rule never scanned `.tsx`
    at all; the `tsx-exported-symbols` sibling rule does."""
    names = _symbol_names(["sample.tsx"])["sample.tsx"]
    # `export default React.memo(Comp)` has no NAME metavariable (the pattern
    # captures $EXPR, not a declared name), so the pre-existing production
    # fallback (deterministic_inventory._parse_matches) derives a name from
    # the signature text — unrelated to this ticket (Q-004 defers symbol
    # `kind`/naming taxonomy work to KLC-108).
    assert names == {"Comp", "Button", "Widget", "export default React.memo"}


def test_js_declaration_forms_exact_symbol_set():
    """AC-1/D-1: the JS-specific narrower rule (exported-symbols-js.yaml)
    still captures every plain-JS top-level export form."""
    names = _symbol_names(["sample.js"])["sample.js"]
    assert names == {"PLAIN", "fn", "Foo", "Named", "Bar"}


def test_barrel_reexport_not_counted_as_symbol():
    """Edge case (Q-002): `export { A, B } from './x'` / `export * from './y'`
    yield no declaration child, so no symbol — a barrel re-export is not an
    authored declaration."""
    names = _symbol_names(["barrel.ts"])["barrel.ts"]
    assert names == set()


def test_ambient_declaration_file_not_scanned_as_source():
    """Edge case: `.d.ts` ambient declarations (`declare const` / `declare
    function`) parse as `ambient_declaration` nodes, not
    `lexical_declaration`/`function_declaration` — the rule's `has:` clauses
    do not match them, so no symbol is pulled from a pure type-declaration
    file."""
    names = _symbol_names(["ambient.d.ts"])["ambient.d.ts"]
    assert names == set()


def test_merged_ts_tsx_js_ruleset_scan_exits_zero():
    """F-1 (HIGH, independent impl-plan review): all three TypeScript-family
    rule files loaded into ONE merged `ast-grep scan` (the same merge
    `_run_astgrep()` performs in production) over a `.ts` + `.tsx` + `.js`
    tree must exit 0 and capture the expected symbols — NOT abort at parse
    time. A literal clone of the TS kind list under `language: javascript`
    fails this exact check (verified independently before this file was
    written: exit 8, 'Kind `abstract_class_declaration` is invalid')."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(
        FIXTURES, ruleset, astgrep,
        files=["sample.ts", "sample.tsx", "sample.js"],
    )
    assert inv["errors"] == [], f"merged scan degraded: {inv['errors']}"
    assert inv["source_of_truth"].get("typescript") == "ast_grep"
    assert inv["source_of_truth"].get("tsx") == "ast_grep"
    assert inv["source_of_truth"].get("javascript") == "ast_grep"
    by_file: dict[str, set[str]] = {}
    for s in inv["symbols"]:
        by_file.setdefault(s["file"], set()).add(s["name"])
    assert by_file["sample.ts"] == {
        "PLAIN", "TYPED", "fn", "generic", "Foo", "Baz", "IFoo", "Alias",
        "Color", "DefaultCls",
    }
    assert by_file["sample.tsx"] == {"Comp", "Button", "Widget",
                                     "export default React.memo"}
    assert by_file["sample.js"] == {"PLAIN", "fn", "Foo", "Named", "Bar"}


# --------------------------------------------------------------------------- #
# KLC-108 step-2 — AC-3: the `module.exports.$NAME = $RHS` clause (the one
# clause in this rule family with no `export_statement`/`kind` anchor) must
# not match once nested inside a function body; a class's own method is not
# collateral damage of the restriction (AC-5).
# --------------------------------------------------------------------------- #
def test_ts_function_body_locals_not_captured():
    """AC-3: `scope.ts`'s in-body `const local` and in-body
    `module.exports.sneaky = local` must not be captured."""
    names = _symbol_names(["scope.ts"])["scope.ts"]
    assert "local" not in names and "sneaky" not in names, names


def test_ts_module_scope_export_still_captured():
    """AC-5 regression guard: the fixture's own top-level exports survive."""
    names = _symbol_names(["scope.ts"])["scope.ts"]
    assert {"add", "MAX", "Widget"} <= names, names


def test_ts_class_method_stays_top_level_surface():
    """Q-003 analogue for TS: `Widget`'s method is not a spurious extra
    capture, and the class itself is unaffected by the restriction."""
    names = _symbol_names(["scope.ts"])["scope.ts"]
    assert "Widget" in names
    assert "render" not in names


def test_tsx_function_body_locals_not_captured():
    """AC-3, `.tsx`: same property via `exported-symbols-tsx.yaml`."""
    names = _symbol_names(["scope.tsx"])["scope.tsx"]
    assert "sneaky" not in names
    assert {"Button", "Comp"} <= names, names


def test_js_function_body_locals_not_captured():
    """AC-3, plain JS: same property via `exported-symbols-js.yaml`."""
    names = _symbol_names(["scope.js"])["scope.js"]
    assert "sneaky" not in names
    assert {"Bar", "PLAIN"} <= names, names
