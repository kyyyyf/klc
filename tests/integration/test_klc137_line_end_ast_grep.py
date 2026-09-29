"""KLC-137 step-2 — the ast-grep path records `line_end` (AC-1, C-003, D-3).

Real-substrate tests: every `line_end` this file checks comes from a real
`build_inventory()` run against a real fixture file, cross-checked against
Python's own `ast` module (never a hand-shaped inventory dict, C-005).
"""
import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import deterministic_inventory as di  # noqa: E402
from deterministic_inventory import match_line_range  # noqa: E402

DI_PATH = SKILLS / "deterministic_inventory.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc137_fixtures import real_inventory, write_python_fixture  # noqa: E402

pytestmark = pytest.mark.usefixtures("hermetic_project_root")


def _ast_nodes_by_name(source: str) -> dict:
    """name -> the ast node (FunctionDef/ClassDef/simple-Name-target Assign)
    that defines it — used to cross-check ast-grep's (line, line_end)."""
    tree = ast.parse(source)
    nodes: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    nodes[t.id] = node
    return nodes


def test_line_end_matches_python_ast_for_decorated_class_and_assignment_symbols(tmp_path):
    """AC-1: every (line, line_end) pair on the ast-grep path equals the same
    named node's (lineno, end_lineno) under Python `ast` — for a decorated
    two-line-signature function, a class with a base and a method, a
    class-body assignment and a multi-line dict assignment — and `line`
    itself is unchanged from today (still the `def`/`class`/assignment
    line, not the decorator's)."""
    root = tmp_path / "proj"
    rel = write_python_fixture(root)
    inv = real_inventory(root, astgrep=True)
    file_symbols = [s for s in inv["symbols"] if s["file"] == rel.as_posix()]
    assert file_symbols, "fixture must yield at least one symbol"

    nodes = _ast_nodes_by_name((root / rel).read_text(encoding="utf-8"))
    checked = set()
    for s in file_symbols:
        node = nodes.get(s["name"])
        assert node is not None, f"no ast node named {s['name']!r}"
        assert s["line"] == node.lineno, s["name"]
        assert s["line_end"] == node.end_lineno, s["name"]
        checked.add(s["name"])
    # every fixture shape actually produced a checked symbol — not a vacuous pass.
    assert {"f", "C", "meth", "x", "CONFIG"} <= checked


def test_line_end_is_json_null_when_astgrep_range_end_line_is_not_an_int():
    """AC-1: `_parse_matches` writes `line_end: null` (not a fabricated int)
    whenever the match's `range.end.line` is missing, a string, or a `bool`
    — and `line` stays whatever the (valid) start computes to. `match_line_range`
    itself returns `None` for every one of these matches too."""
    base_meta = {"single": {"NAME": {"text": "f"}}}

    def _match(end_field):
        rng = {"start": {"line": 3, "column": 0}}
        if end_field is not None:
            rng["end"] = end_field
        return {
            "text": "def f():\n    pass",
            "range": rng,
            "file": "a.py",
            "language": "python",
            "ruleId": "py-public-api",
            "metaVariables": base_meta,
        }

    matches = [
        _match(None),                          # range.end missing entirely
        _match({"column": 0}),                 # range.end.line missing
        _match({"line": "5", "column": 0}),     # range.end.line a string
        _match({"line": True, "column": 0}),    # range.end.line a bool
    ]
    out = di._parse_matches(matches, "ast_grep")
    assert len(out) == len(matches)
    for m, sym in zip(matches, out):
        assert sym["line"] == 4          # start (3) + 1, unaffected by the bad end
        assert sym["line_end"] is None
        assert match_line_range(m) is None


def test_match_line_range_is_the_single_conversion_site():
    """AC-1, C-003: only `_one_based` adds 1 to a position; `_parse_matches`,
    `match_line_range` and `_regex_symbol` never do, and the first two call
    it — so there is exactly one place a 0-based ast-grep line becomes a
    1-based editor line (D-101)."""
    tree = ast.parse(DI_PATH.read_text(encoding="utf-8"))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def plus_ones(fn):
        return [b for b in ast.walk(fn) if isinstance(b, ast.BinOp)
                and isinstance(b.op, ast.Add)
                and isinstance(b.right, ast.Constant) and b.right.value == 1]

    def calls(fn):
        return {c.func.id for c in ast.walk(fn)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}

    assert len(plus_ones(fns["_one_based"])) == 1
    for name in ("_parse_matches", "match_line_range", "_regex_symbol"):
        assert plus_ones(fns[name]) == [], name
    assert "_one_based" in calls(fns["_parse_matches"])
    assert "_one_based" in calls(fns["match_line_range"])


_CPP_FIXTURE = (
    "// C++ fixture for KLC-137 D-3 (hand-written ground truth)\n"
    "\n"
    "class Widget {\n"
    "public:\n"
    "  virtual void draw() const\n"
    "      = 0;\n"
    "  int x;\n"
    "};\n"
    "\n"
    "struct Point {\n"
    "  int x;\n"
    "  int y;\n"
    "};\n"
)

_RUST_FIXTURE = (
    "pub struct Config {\n"
    "    pub x: i32,\n"
    "}\n"
    "\n"
    "pub fn build(\n"
    "    a: i32,\n"
    "    b: i32,\n"
    ") -> i32 {\n"
    "    a + b }\n"
    "\n"
    "pub enum Shape {\n"
    "    Circle,\n"
    "}\n"
)


def test_cpp_fixture_line_end_matches_hand_written_ranges(tmp_path):
    """D-3: a hand-written C++ header fixture, scanned with the real
    `core/rules/cpp` ruleset, pins `line_end` for an ast-grep-backed
    non-Python language — expected pairs are literals (F-104): Widget 3-8,
    Point 10-13, draw 5-6 (1-based inclusive)."""
    (tmp_path / "widget.h").write_text(_CPP_FIXTURE, encoding="utf-8")
    ruleset = {
        "profile": "test",
        "rule_dirs": [str(REPO_ROOT / "core" / "rules" / "cpp")],
        "excludes_re": "",
        "language_globs": {"cpp": ["*.h"]},
    }
    inv = real_inventory(tmp_path, astgrep=True, ruleset=ruleset)
    by_name = {s["name"]: (s["line"], s["line_end"]) for s in inv["symbols"]}
    assert by_name["Widget"] == (3, 8)
    assert by_name["Point"] == (10, 13)
    assert by_name["draw"] == (5, 6)


def test_rust_fixture_line_end_matches_hand_written_ranges(tmp_path):
    """D-3: a hand-written Rust fixture, scanned with the real
    `core/rules/rust` ruleset — expected pairs are literals (F-104):
    Config 1-3, build 5-9, Shape 11-13 (1-based inclusive)."""
    (tmp_path / "lib.rs").write_text(_RUST_FIXTURE, encoding="utf-8")
    ruleset = {
        "profile": "test",
        "rule_dirs": [str(REPO_ROOT / "core" / "rules" / "rust")],
        "excludes_re": "",
        "language_globs": {},
    }
    inv = real_inventory(tmp_path, astgrep=True, ruleset=ruleset)
    by_name = {s["name"]: (s["line"], s["line_end"]) for s in inv["symbols"]}
    assert by_name["Config"] == (1, 3)
    assert by_name["build"] == (5, 9)
    assert by_name["Shape"] == (11, 13)


def test_trailing_comment_line_is_inside_the_ast_grep_range(tmp_path):
    """ADR D-203: a class whose last body line is a trailing comment — the
    comment sits INSIDE the tree-sitter node ast-grep matches, so `line_end`
    is that comment line, one more than Python `ast`'s `end_lineno` (which
    does not count a trailing comment as part of the node)."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    src = (
        "class D:\n"
        "    def m(self):\n"
        "        return 1\n"
        "        # trailing comment inside the block\n"
    )
    (root / "pkg" / "trailing.py").write_text(src, encoding="utf-8")
    inv = real_inventory(root, astgrep=True)
    by_name = {s["name"]: (s["line"], s["line_end"])
               for s in inv["symbols"] if s["file"] == "pkg/trailing.py"}

    tree = ast.parse(src)
    d_node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "D")
    assert d_node.end_lineno == 3        # ast stops at `return 1`
    assert by_name["D"] == (1, 4)        # ast-grep's range includes the comment line
    assert by_name["D"][1] == d_node.end_lineno + 1
