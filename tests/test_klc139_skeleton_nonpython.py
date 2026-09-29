"""KLC-139 step-5 — the ast-grep engine: rule-scoped outline for non-Python
files (AC-6, plus AC-5/AC-9 cross-cutting cases).

Real-substrate: the oracle test runs ast-grep itself, through the SAME
`deterministic_inventory.resolve_ruleset()` the engine uses, and cross-checks
its own line ranges independently of `skeleton.match_line_range` conversion.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skeleton as sk  # noqa: E402
import deterministic_inventory as di  # noqa: E402
import tools  # noqa: E402
import profile_cache  # noqa: E402


@contextmanager
def _short_root(monkeypatch):
    """A short-named tmp dir (unlike pytest's nested `tmp_path`), so a
    header's `rule-scoped` suffix (62 chars) does not spuriously push an
    otherwise-short fixture path past `max_line` (D-208 is about intentional
    long paths, not pytest's own directory nesting)."""
    with tempfile.TemporaryDirectory(prefix="k139-") as root:
        monkeypatch.setenv("PROJECT_ROOT", root)
        yield Path(root)


def _astgrep_or_skip() -> str:
    p = tools.resolve_tool("ast-grep")
    if not p:
        pytest.skip("ast-grep not installed in this environment")
    return str(p)


def _oracle_ranges(fixture: Path) -> set:
    """(ruleId, start, end) for every real ast-grep match on *fixture*,
    through the SAME resolve_ruleset() the engine uses — independent of
    `_group_by_rule`."""
    astgrep = _astgrep_or_skip()
    ruleset = di.resolve_ruleset()
    cfg = {"ruleDirs": ruleset["rule_dirs"]}
    if ruleset["language_globs"]:
        cfg["languageGlobs"] = ruleset["language_globs"]
    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "sgconfig.yml"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        r = subprocess.run(
            [astgrep, "scan", "--config", str(cfg_path), "--json=compact", str(fixture)],
            capture_output=True, text=True, cwd=td, timeout=60,
        )
    raw = json.loads(r.stdout or "[]")
    out = set()
    for m in raw:
        rng = di.match_line_range(m)
        if rng:
            out.add((m.get("ruleId"), rng[0], rng[1]))
    return out


def _rendered_ranges(text: str) -> set:
    """Parse `(ruleId, start, end)` back out of a rendered rule-scoped
    outline."""
    out = set()
    current_rule = None
    for line in text.splitlines()[1:]:
        if not line.startswith(" "):
            current_rule = line.split(":", 1)[0]
            continue
        m = re.search(r"\[(\d+)(?:-(\d+))?\]\s*$", line)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
            out.add((current_rule, start, end))
    return out


_TS_FIXTURE = (
    "export function ok() {\n"
    "  return 1;\n"
    "}\n"
    "async function hidden() {}\n"
)
_RS_FIXTURE = (
    "pub fn ok() -> i32 {\n"
    "    1\n"
    "}\n"
    "\n"
    "fn hidden() -> i32 {\n"
    "    2\n"
    "}\n"
)
_H_FIXTURE = (
    "class Foo {\n"
    "public:\n"
    "    void bar();\n"
    "};\n"
)


@pytest.mark.parametrize(
    "name,source",
    [("good.ts", _TS_FIXTURE), ("l.rs", _RS_FIXTURE), ("w.h", _H_FIXTURE)],
)
def test_golden_ts_rs_h_match_astgrep_ranges(tmp_path, monkeypatch, name, source):
    """AC-6: skeleton()'s reported (rule, start, end) set for a .ts/.rs/.h
    fixture matches ast-grep's own ranges exactly."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / name
    fixture.write_text(source, encoding="utf-8")
    oracle = _oracle_ranges(fixture)
    assert oracle, "the oracle itself found nothing — fixture needs a real match"

    result = sk.skeleton(str(fixture))
    assert not result.refused
    assert _rendered_ranges(result.text) == oracle


def test_identical_matches_collapse_to_one_entry(tmp_path, monkeypatch):
    """AC-6: two raw matches with the same (rule, start, end) collapse to
    one printed entry (F-207: an `any:` rule over export_statement and
    function_declaration matches the same function twice)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "dup.yaml").write_text(
        "id: dup-rule\n"
        "language: TypeScript\n"
        "message: duplicate-prone rule\n"
        "rule:\n"
        "  any:\n"
        "    - kind: export_statement\n"
        "    - kind: function_declaration\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "f.ts"
    fixture.write_text("export function f() {\n  return 1;\n}\n", encoding="utf-8")

    _astgrep_or_skip()
    payload = {
        "root": str(tmp_path),
        "identity": {"name": "tmp-dup", "fields_sha256": "0" * 64},
        "fields": {"name": "tmp-dup", "rules": str(rules_dir),
                   "sgconfig": "", "excludes-regex": ""},
    }
    with profile_cache.run_scope(payload):
        result = sk.skeleton(str(fixture))
    assert result.text.count("export function f() [1-3]") == 1


def test_rule_header_shows_id_and_message_under_rule_neutral_top_header(tmp_path, monkeypatch):
    """AC-6: the top header says `rule-scoped`, never `public`/`exported`;
    a NON-exported `async function` is grouped under its own rule id and
    message, next to the exported-symbols rule."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "mixed.ts"
    fixture.write_text(_TS_FIXTURE, encoding="utf-8")
    result = sk.skeleton(str(fixture))
    header = result.text.splitlines()[0]
    assert "rule-scoped" in header
    assert "public" not in header
    assert "exported" not in header
    assert "ts-async-patterns: Async function / arrow boundary" in result.text
    assert "ts-exported-symbols: Exported TS declaration" in result.text


def test_source_has_no_hardcoded_language_or_extension_literal():
    """AC-6/AC-9 (review F-7): `skeleton.py` names no language or extension
    other than `.py`/`.pyi`, so a new language needs an ast-grep rule, never
    a `skeleton.py` edit."""
    source = (SKILLS / "skeleton.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring_nodes = set()
    _DOCABLE = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, _DOCABLE):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc is not None and node.body and isinstance(node.body[0], ast.Expr):
            docstring_nodes.add(id(node.body[0].value))

    ext_tokens = {"ts", "tsx", "js", "jsx", "mjs", "rs", "h", "hpp", "hxx",
                  "cc", "cpp", "go", "java", "kt", "rb", "cs"}
    lang_names = {"typescript", "tsx", "javascript", "rust", "cpp", "go",
                  "java", "kotlin", "ruby", "csharp", "swift", "scala",
                  "lua", "php", "bash"}
    ext_re = re.compile(r"^\.\w+$")
    glob_re = re.compile(r"\*\.\w+")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstring_nodes:
            continue
        value = node.value
        if ext_re.fullmatch(value):
            assert value in (".py", ".pyi"), f"forbidden extension literal: {value!r}"
        assert not glob_re.search(value), f"forbidden glob literal: {value!r}"
        assert value.lower() not in ext_tokens, f"forbidden extension token: {value!r}"
        lowered = value.lower()
        for name in lang_names:
            if re.search(rf"\b{name}\b", lowered):
                raise AssertionError(f"forbidden language name {name!r} in {value!r}")


def test_rule_group_is_not_capped(monkeypatch):
    """AC-5/Q-001: a rule group is NEVER capped — a .ts with 10 exports
    lists all 10 entries, no `truncated`."""
    with _short_root(monkeypatch) as root:
        body = "\n".join(f"export function f{i}() {{ return {i}; }}" for i in range(10))
        fixture = root / "many.ts"
        fixture.write_text(body + "\n", encoding="utf-8")
        result = sk.skeleton(str(fixture))
    for i in range(10):
        assert f"f{i}()" in result.text
    assert "truncated" not in result.text


def test_long_path_header_keeps_rule_scoped_label(tmp_path, monkeypatch):
    """AC-6 with AC-5 (review F-4): a .ts at a 150-character path gives a
    header of at most `max_line` characters that still ends with the
    `rule-scoped` suffix intact."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    long_stem = "p" * 150
    fixture = tmp_path / f"{long_stem}.ts"
    fixture.write_text("export function ok() {}\n", encoding="utf-8")
    result = sk.skeleton(str(fixture))
    header = result.text.splitlines()[0]
    assert len(header) <= 120
    assert header.endswith("(typescript, rule-scoped: only what the profile's rules match)")
