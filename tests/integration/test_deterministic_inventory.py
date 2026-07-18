"""KLC-070 step-1 — deterministic inventory skill.

Real-substrate tests: run the actual ast-grep path against a temp fixture repo and
exercise the regex-degrade path by passing astgrep_path=None. Freezes the inventory
JSON schema that KLC-071 depends on.
"""
import json
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import deterministic_inventory as di  # noqa: E402

_FROZEN_SYMBOL_FIELDS = {
    "name", "kind", "file", "line", "signature", "visibility",
    "source_of_truth", "lang", "rule",
}


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text(
        "def public_fn(a, b):\n"
        "    return a + b\n\n"
        "class PublicThing:\n"
        "    pass\n\n"
        "def _private_fn():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    return root


def _astgrep_or_skip():
    import tools
    p = tools.resolve_tool("ast-grep")
    if not p:
        import pytest
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def test_writes_symbols_from_astgrep(tmp_path):
    """AC-1: ast-grep path yields the frozen symbol schema."""
    root = _fixture(tmp_path)
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(root, ruleset, astgrep)

    assert inv["source_of_truth"].get("python") == "ast_grep"
    names = {s["name"] for s in inv["symbols"]}
    assert "public_fn" in names
    assert "PublicThing" in names
    # Every symbol carries the full frozen schema.
    for s in inv["symbols"]:
        assert set(s) == _FROZEN_SYMBOL_FIELDS
    fn = next(s for s in inv["symbols"] if s["name"] == "public_fn")
    assert fn["kind"] == "function"
    assert fn["visibility"] == "public"
    assert fn["source_of_truth"] == "ast_grep"
    assert fn["file"] == "pkg/mod.py"
    assert fn["line"] == 1


def test_astgrep_is_deterministic(tmp_path):
    """AC-11: byte-identical payload on re-run (no inner timestamp)."""
    root = _fixture(tmp_path)
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    a = di.build_inventory(root, ruleset, astgrep)
    b = di.build_inventory(root, ruleset, astgrep)
    assert json.dumps(a) == json.dumps(b)
    assert "generated_at" not in a  # timestamp only added by main() at top level


def test_regex_degrade_when_astgrep_absent(tmp_path):
    """AC-3: astgrep_path=None → regex fallback, errors[] populated, still produces."""
    root = _fixture(tmp_path)
    ruleset = di.resolve_ruleset()
    inv = di.build_inventory(root, ruleset, None)

    assert inv["source_of_truth"].get("python") == "regex"
    assert any("regex" in e.lower() for e in inv["errors"])
    names = {s["name"] for s in inv["symbols"]}
    assert "public_fn" in names and "PublicThing" in names
    assert "_private_fn" not in names  # fallback keeps the public-only convention
    for s in inv["symbols"]:
        assert s["source_of_truth"] == "regex"
        assert set(s) == _FROZEN_SYMBOL_FIELDS


def test_astgrep_path_honours_profile_excludes(tmp_path):
    """FIX-1 (codex P2): a file under a profile-excluded dir must NOT appear on the
    ast-grep path (it already didn't on the regex path)."""
    root = _fixture(tmp_path)
    # active profile 'ue' excludes Content/ (Binaries, Intermediate, Content, ...).
    (root / "Content").mkdir()
    (root / "Content" / "gen.py").write_text(
        "def generated_thing():\n    return 0\n", encoding="utf-8")
    ruleset = di.resolve_ruleset()
    assert ruleset["excludes_re"], "test assumes the active profile has excludes"
    astgrep = _astgrep_or_skip()

    inv_ast = di.build_inventory(root, ruleset, astgrep)
    names_ast = {s["name"] for s in inv_ast["symbols"]}
    assert "public_fn" in names_ast
    assert "generated_thing" not in names_ast, "excluded dir leaked into ast-grep path"

    # Regex path must agree (parity).
    inv_rx = di.build_inventory(root, ruleset, None)
    assert "generated_thing" not in {s["name"] for s in inv_rx["symbols"]}


def test_exit2_on_bad_root(tmp_path):
    """CLI contract: --root that is not a directory exits 2."""
    bad = tmp_path / "nope"
    rc = di.main(["--root", str(bad), "--out", str(tmp_path / "out.json")])
    assert rc == 2


def test_main_writes_file_and_top_level_timestamp(tmp_path):
    """main() writes inventory.json with generated_at only at the top level."""
    root = _fixture(tmp_path)
    out = tmp_path / "inventory.json"
    rc = di.main(["--root", str(root), "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "generated_at" in data
    assert isinstance(data["symbols"], list)
    for s in data["symbols"]:
        assert "generated_at" not in s
