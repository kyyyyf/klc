"""KLC-108 — the Rust rule set (`core/rules/rust/exported-symbols.yaml`)
captures only module-scope `pub` items, never a declaration nested inside a
function body (AC-3). The merged-ruleset test below is
`[!DECISION D-108-2]`, resolving impl-plan-review finding F-1 (medium): the
merged ruleset (every rule dir the active profile resolves, loaded into ONE
`ast-grep scan`, C-001) still parses and scans cleanly when scanning a REAL
Rust fixture — the same proof `tests/test_rules_typescript.py
::test_merged_ts_tsx_js_ruleset_scan_exits_zero` already gives for the
TypeScript family, extended here so a scope-clause typo in the Rust file
(or any sibling) is caught by a test that actually exercises Rust source,
not only by an unrelated TS-only smoke test that happens to load the same
merged config.

Real-substrate: the REAL rule file, through the REAL production scan path
(`deterministic_inventory.build_inventory`) — no ad-hoc sgconfig.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rules" / "rust"

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


def test_rust_function_body_locals_not_captured():
    """AC-3: `helper`, a `pub fn` NESTED inside another `pub fn`'s body, must
    not be captured — the exact case D-001's code sketch names."""
    names = _symbol_names(["scope.rs"])["scope.rs"]
    assert "helper" not in names, names


def test_rust_pub_module_scope_still_captured():
    """AC-5 regression guard: the fixture's own top-level `pub fn`/`pub
    struct` still match."""
    names = _symbol_names(["scope.rs"])["scope.rs"]
    assert {"add", "Point"} <= names, names


def test_merged_ruleset_scan_exits_zero_rust_fixtures():
    """[!DECISION D-108-2] (impl-plan-review F-1, medium): the FULL merged
    ruleset — every rule dir `deterministic_inventory.resolve_ruleset()`
    resolves for the active profile, all loaded into ONE `ast-grep scan`
    (C-001) — must exit 0 and capture the expected symbols when scanning a
    REAL Rust fixture, not abort to the regex fallback. A rule-file parse
    error in ANY sibling language (Python/TS/C++) would abort this scan too,
    so this is a genuine whole-profile parse-safety proof, exercised through
    Rust source specifically (test_rules_typescript.py's existing merged
    smoke test only ever scans .ts/.tsx/.js fixtures)."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(FIXTURES, ruleset, astgrep, files=["scope.rs"])
    assert inv["errors"] == [], f"merged scan degraded: {inv['errors']}"
    assert inv["source_of_truth"].get("rust") == "ast_grep"
    names = {s["name"] for s in inv["symbols"] if s["file"] == "scope.rs"}
    assert names == {"add", "Point"}, names
