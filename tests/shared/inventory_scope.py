"""tests/shared/inventory_scope.py — KLC-108 step-3 (AC-4): pure helpers
resolving inventory symbols against a file's parsed Python function-body
ranges. No production code depends on this module — it exists so the
repository-wide scope ASSERTION (an independent, oracle-backed check) and
its fail-closed twin share one implementation rather than each reinventing
"is this line inside a function body".
"""
from __future__ import annotations

import ast
from pathlib import Path


def function_body_ranges(source: str) -> list[tuple[int, int]]:
    """Inclusive (first, last) line of every function/method BODY in
    *source*. A class body is NOT a function body (Q-003) — a method's own
    body is (its `def` is itself a FunctionDef, so its body is walked too),
    but the class's own suite (attributes, nested class-scope assignments)
    is not, so those stay top level. Returns `[]` on a syntax error rather
    than raising — a symbol resolved against an unparseable file cannot be
    proven in-body, so it is never falsely flagged (fail-closed the other
    direction: `in_body_symbols` below then reports it neither way, which is
    correct — an assertion of a POSITIVE property (0 violations) must not
    manufacture a violation out of a file it cannot parse)."""
    out: list[tuple[int, int]] = []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0].lineno
            last = first
            for child in node.body:
                for sub in ast.walk(child):
                    end = getattr(sub, "end_lineno", None) or getattr(sub, "lineno", first)
                    if end > last:
                        last = end
            out.append((first, last))
    return out


def in_body_symbols(inventory: dict, root: Path) -> list[dict]:
    """Every Python symbol in *inventory* whose recorded `line` falls inside
    a parsed function-body range of its own file (resolved under *root*).
    Non-Python files and symbols with no usable `line` are skipped (this
    assertion's oracle is Python's own `ast` module — spec A-3 — it makes no
    claim about the other languages)."""
    out: list[dict] = []
    cache: dict[str, list[tuple[int, int]]] = {}
    for sym in (inventory or {}).get("symbols") or []:
        f = sym.get("file") or ""
        if not f.endswith(".py"):
            continue
        line = sym.get("line")
        if not isinstance(line, int):
            continue
        if f not in cache:
            try:
                text = (Path(root) / f).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                cache[f] = []
            else:
                cache[f] = function_body_ranges(text)
        if any(lo <= line <= hi for lo, hi in cache[f]):
            out.append(sym)
    return out
