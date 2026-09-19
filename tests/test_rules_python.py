"""KLC-108 — the Python rule set (`core/rules/python/public-api.yaml`,
`class-hierarchy.yaml`) captures only top-level/class-scope declarations,
and captures the annotated forms it missed before step-1's re-anchor.

Real-substrate tests: the REAL rule files, through the REAL production scan
path (`deterministic_inventory.build_inventory`, the same function `klc
init` calls) — no ad-hoc sgconfig, no mocked ast-grep output. Mirrors the
pattern already established by `tests/test_rules_typescript.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rules" / "python"

sys.path.insert(0, str(SKILLS))
import deterministic_inventory as di  # noqa: E402
import tools  # noqa: E402


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def _symbol_names(files: list[str]) -> dict[str, set[str]]:
    """Run the REAL merged ruleset (active profile) over *files* under the
    fixture dir, through the production build_inventory() path."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(FIXTURES, ruleset, astgrep, files=files)
    out: dict[str, set[str]] = {f: set() for f in files}
    for s in inv["symbols"]:
        if s["file"] in out:
            out[s["file"]].add(s["name"])
    return out


# --------------------------------------------------------------------------- #
# step-1 — F-002 / [!CONFLICT C-101]: annotated definitions were missed by
# the literal-text rule; the re-anchored (kind-based) rule captures them.
# --------------------------------------------------------------------------- #
def test_python_annotated_definitions_are_captured():
    """[!CONFLICT C-101] resolved by D-201: the return-annotated, typed-arg
    and async-annotated forms all enter the inventory once the rule is
    anchored on `kind: function_definition` instead of a literal `def
    $NAME($$$ARGS): $$$BODY` text pattern (F-002)."""
    names = _symbol_names(["sample.py"])["sample.py"]
    assert {"annotated", "typed_args", "a_annotated"} <= names, names


def test_python_module_scope_constant_still_captured():
    """AC-5 regression guard: recall for the pre-existing unannotated/class/
    constant forms must not regress when the rule is re-anchored."""
    names = _symbol_names(["sample.py"])["sample.py"]
    assert {"plain", "Point", "MAX_SIZE"} <= names, names


# --------------------------------------------------------------------------- #
# step-2 — AC-2: no assignment target, parameter or nested definition
# declared inside a function/method body; AC-5 (Q-003): class methods and
# class-scope constants are NOT "inside a function body" and stay captured.
# --------------------------------------------------------------------------- #
def test_python_module_scope_names_only():
    """AC-2: the fixture's exact module/class-scope name set, nothing more —
    `out`, `argv`, `d`, `helper`, `nested` must all be absent."""
    names = _symbol_names(["scope.py"])["scope.py"]
    assert names == {"MAX_SIZE", "Config", "DEFAULT", "method", "run"}, names


def test_python_function_body_locals_not_captured():
    """Negative twin: same fixture, each local individually absent — including
    `helper`, a nested `def` (a declaration form the rule DOES capture at
    module scope), and `nested`, declared two function-bodies deep."""
    names = _symbol_names(["scope.py"])["scope.py"]
    for local in ("out", "argv", "d", "helper", "nested"):
        assert local not in names, f"{local} leaked into {names}"


def test_python_class_method_stays_top_level_surface():
    """Q-003: a class's `def` methods and class-scope assignments are not
    "inside a function body" — the scope restriction must not collaterally
    exclude them."""
    names = _symbol_names(["scope.py"])["scope.py"]
    assert {"method", "DEFAULT"} <= names, names
