"""KLC-108 — AC-1: every rule file under `core/rules` and `profiles/*/rules`
declares, and the executor proves, an `invalid` case whose snippet places the
captured declaration form inside a function or method body.

Detection convention: the in-body case is identified by a literal marker
comment, ``KLC-108 AC-1: in-body case``, as the FIRST LINE of the snippet's
own source text — a genuine, harmless comment in that snippet's language
(``#`` for Python, ``//`` for TypeScript/JavaScript/Rust/C++). This is
deliberately explicit rather than inferred from indentation/keyword
heuristics per language: F-007 (`design/options.md`) already showed a
heuristically-"nested" snippet can silently fail to parse as nested at all
(it falls under a tree-sitter ERROR node instead of the real function-body
node) and so pass the gate for the wrong reason. The marker makes "this is
the KLC-108 in-body proof case" a fact stated in the fixture itself, checked
by the SAME production executor (`tests.rule_test_executor.run_rule_tests`)
every other case in this suite runs through — not a second, parallel
detector.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_ROOT = REPO_ROOT / "tests"

sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "skills"))

from rule_test_executor import run_rule_tests  # noqa: E402

_MARKER = "KLC-108 AC-1: in-body case"


def _discover_rule_files() -> list[Path]:
    """AC-1's own file set: `core/rules/**/*.yaml` plus `profiles/*/rules/
    **/*.yaml` when a profile carries any (none does today — KLC-122 removed
    the UE profile; D-OP-1 records that AC-1's `profiles/*/rules` clause is
    then satisfied vacuously)."""
    files = sorted((REPO_ROOT / "core" / "rules").rglob("*.yaml"))
    profiles_dir = REPO_ROOT / "profiles"
    if profiles_dir.is_dir():
        files += sorted(profiles_dir.glob("*/rules/**/*.yaml"))
    return files


_RULE_FILES = _discover_rule_files()
_RULE_FILE_IDS = [str(p.relative_to(REPO_ROOT)) for p in _RULE_FILES]


def _load_doc(rule_file: Path) -> dict:
    import yaml
    return yaml.safe_load(rule_file.read_text(encoding="utf-8")) or {}


def _in_body_case_index(doc: dict) -> int | None:
    """Index into ``tests.invalid`` of the case carrying the KLC-108 marker,
    or None when no case carries it (the fail-closed path)."""
    invalid_cases = (doc.get("tests") or {}).get("invalid") or []
    for i, snippet in enumerate(invalid_cases):
        if _MARKER in (snippet or ""):
            return i
    return None


def _astgrep_or_skip():
    import tools
    if not tools.resolve_tool("ast-grep"):
        pytest.skip("ast-grep not installed in this environment")


def _active_profile_language_globs() -> dict:
    import deterministic_inventory as di
    return di.resolve_ruleset().get("language_globs") or {}


@pytest.mark.parametrize("rule_file", _RULE_FILES, ids=_RULE_FILE_IDS)
def test_every_rule_file_has_in_body_invalid_case(rule_file):
    doc = _load_doc(rule_file)
    idx = _in_body_case_index(doc)
    assert idx is not None, (
        f"{rule_file}: no `invalid` case carries the {_MARKER!r} marker — "
        f"AC-1 requires one case placing the captured declaration form "
        f"inside a function/method body")


@pytest.mark.parametrize("rule_file", _RULE_FILES, ids=_RULE_FILE_IDS)
def test_in_body_invalid_case_yields_zero_matches_via_executor(rule_file):
    """Runs the SAME production executor every other rule test in this suite
    uses (`run_rule_tests`, over the rule file's own directory), and asserts
    specifically that the in-body case (identified by `_in_body_case_index`)
    is not among the reported failures — the case must yield zero matches."""
    _astgrep_or_skip()
    doc = _load_doc(rule_file)
    idx = _in_body_case_index(doc)
    if idx is None:
        pytest.skip(f"{rule_file}: no in-body case — covered by the sibling "
                    f"'declares' test")
    failures = run_rule_tests([rule_file.parent], _active_profile_language_globs())
    tag = f"[invalid #{idx}]"
    hit = [f for f in failures if rule_file.name in f and tag in f]
    assert hit == [], (
        f"{rule_file}: in-body case at invalid #{idx} matched when it must "
        f"not — {hit}")


def test_rule_file_missing_in_body_invalid_case_fails_the_gate(tmp_path):
    """Fail-closed twin: a synthetic rule file with only top-level cases (no
    marker) must be reported as a violation by `_in_body_case_index` — the
    exact helper `test_every_rule_file_has_in_body_invalid_case` uses —
    never silently treated as covered."""
    synthetic = tmp_path / "no-in-body.yaml"
    synthetic.write_text(
        "id: synthetic-no-in-body\n"
        "language: python\n"
        "metadata:\n"
        "  extensions: ['.py']\n"
        "rule:\n"
        "  pattern: \"$NAME = $RHS\"\n"
        "tests:\n"
        "  valid:\n"
        "    - |\n"
        "      X = 1\n"
        "  invalid:\n"
        "    - |\n"
        "      _hidden = 1\n",
        encoding="utf-8")
    doc = _load_doc(synthetic)
    assert _in_body_case_index(doc) is None
