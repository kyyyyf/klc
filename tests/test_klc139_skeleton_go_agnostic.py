"""KLC-139 step-5 — AC-9: language-agnosticism. A synthetic ast-grep rule for
Go (a language no built-in rule covers) proves `skeleton.py` needs no change
to support a new language — only a rule.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skeleton as sk  # noqa: E402
import tools  # noqa: E402
import profile_cache  # noqa: E402


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def _go_payload(tmp_path: Path, rules_dir: Path) -> dict:
    return {
        "root": str(tmp_path),
        "identity": {"name": "tmp-go", "fields_sha256": "0" * 64},
        "fields": {"name": "tmp-go", "rules": str(rules_dir),
                   "sgconfig": "", "excludes-regex": ""},
    }


def test_synthetic_go_rule_in_tmp_profile_returns_ranges_no_skeleton_py_change(
    tmp_path, monkeypatch
):
    """AC-9: a tmp `go-funcs` rule (`kind: function_declaration`) returns
    ranges for a Go fixture, and `skeleton.py`'s sha256 is unchanged by this
    test — no monkeypatch of skeleton.py itself, no production module
    patched beyond the profile hand-down (D-205)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _astgrep_or_skip()

    before = hashlib.sha256((SKILLS / "skeleton.py").read_bytes()).hexdigest()

    rules_dir = tmp_path / "go_rules"
    rules_dir.mkdir()
    (rules_dir / "go-funcs.yaml").write_text(
        "id: go-funcs\n"
        "language: Go\n"
        "message: Go function declaration\n"
        "rule:\n"
        "  kind: function_declaration\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "main.go"
    fixture.write_text(
        "package main\n"
        "\n"
        "func main() {\n"
        "\thelper()\n"
        "}\n"
        "\n"
        "func helper() int {\n"
        "\treturn 1\n"
        "}\n",
        encoding="utf-8",
    )

    with profile_cache.run_scope(_go_payload(tmp_path, rules_dir)):
        result = sk.skeleton(str(fixture))

    assert not result.refused
    assert "func main() [3-5]" in result.text
    assert "func helper() int [7-9]" in result.text

    after = hashlib.sha256((SKILLS / "skeleton.py").read_bytes()).hexdigest()
    assert before == after


def test_broken_go_fixture_refused_as_syntax_error(tmp_path, monkeypatch):
    """AC-9: a syntactically broken Go fixture is refused as a syntax error,
    through the same `kind: ERROR` probe every language uses."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _astgrep_or_skip()

    rules_dir = tmp_path / "go_rules"
    rules_dir.mkdir()
    (rules_dir / "go-funcs.yaml").write_text(
        "id: go-funcs\n"
        "language: Go\n"
        "message: Go function declaration\n"
        "rule:\n"
        "  kind: function_declaration\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "broken.go"
    fixture.write_text("package main\n\nfunc main( {\n", encoding="utf-8")

    with profile_cache.run_scope(_go_payload(tmp_path, rules_dir)):
        result = sk.skeleton(str(fixture))

    assert result.exit_code == 1
    assert result.text == f"{fixture}: syntax errors — read the file instead\n"
