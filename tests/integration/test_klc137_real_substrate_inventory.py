"""KLC-137 step-2 — AC-13 (first clause): real-substrate ground truth.

Runs the post-ticket builder over the `fresh_index` mirror of THIS repo's
own tracked `core/` tree (no bootstrap exemption — a symbol like
`match_line_range`, added by this very ticket, is checked the same as any
other) and cross-checks every Python (line, line_end) against Python's own
`ast` module. Per the operator ruling on C-101 (2026-09-29), the relaxed
rule applies: `line == node.lineno`, `node.end_lineno <= line_end <= file
length`, and every line strictly after `node.end_lineno` up to `line_end`
is blank or comment-only.
"""
import ast
import json
from pathlib import Path


def _nodes_by_name(source: str) -> dict:
    tree = ast.parse(source)
    nodes: dict[str, list] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    nodes.setdefault(t.id, []).append(node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                nodes.setdefault(node.target.id, []).append(node)
    return nodes


def test_every_python_symbol_line_and_line_end_matches_ast_over_the_core_tree(fresh_index):
    """AC-13, first clause: every Python symbol the post-ticket builder
    produced with ast-grep over `core/`, read from the `fresh_index`
    mirror's real inventory.json, matches Python `ast`'s own
    lineno/end_lineno for the node of that name at that line."""
    mirror_root = fresh_index.parent.parent
    inv = json.loads((fresh_index / "inventory.json").read_text(encoding="utf-8"))
    core_py_symbols = [
        s for s in inv["symbols"]
        if s.get("lang") == "python"
        and s.get("source_of_truth") == "ast_grep"
        and s.get("file", "").startswith("core/")
    ]
    assert core_py_symbols, "fresh_index mirror must contain core/ Python ast-grep symbols"

    by_file: dict[str, list[dict]] = {}
    for s in core_py_symbols:
        by_file.setdefault(s["file"], []).append(s)

    checked = 0
    for rel, syms in by_file.items():
        source = (mirror_root / rel).read_text(encoding="utf-8")
        # KLC-137 step-7 review-fix (external LOW): split on '\n' only —
        # str.splitlines() also splits on U+2028/U+0085/\x0c etc., which
        # ast/ast-grep do not treat as line breaks.
        lines = source.split("\n")
        nodes = _nodes_by_name(source)
        for s in syms:
            candidates = nodes.get(s["name"], [])
            node = next((n for n in candidates if n.lineno == s["line"]), None)
            assert node is not None, (
                f"{rel}: no ast node named {s['name']!r} at line {s['line']}")
            assert s["line"] == node.lineno, (rel, s["name"])
            line_end = s["line_end"]
            assert node.end_lineno <= line_end <= len(lines), (rel, s["name"], line_end)
            for lineno in range(node.end_lineno + 1, line_end + 1):
                text = lines[lineno - 1].strip()
                assert text == "" or text.startswith("#"), (rel, s["name"], lineno, text)
            checked += 1
    assert checked == len(core_py_symbols)
