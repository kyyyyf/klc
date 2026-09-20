"""tests/integration/test_klc109_guard.py — KLC-109 step-7, AC-12: a guard
test that fails when any module outside core/skills/test_conventions.py
defines a test-path predicate or a test-path pattern literal.
"""
from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "core" / "skills"

_TOKENS = ("__tests__", "_test", ".test.", ".spec.", "_spec")
_PATTERN_CALLS = {"compile", "search", "match", "fullmatch", "findall", "sub",
                  "startswith", "endswith", "glob", "rglob"}


def _docstring_ids(tree: ast.AST) -> set[int]:
    """id()s of every Constant node that is a module/class/function docstring
    (its FIRST body statement) — prose mentioning a test token is not a
    pattern."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _in_pattern_call(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """True when *node* is (transitively, up to the enclosing call) an
    argument of a call whose name is one of _PATTERN_CALLS (re.compile,
    str.startswith, Path.glob, ...)."""
    cur = parents.get(id(node))
    hops = 0
    while cur is not None and hops < 4:
        if isinstance(cur, ast.Call):
            func = cur.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if name in _PATTERN_CALLS:
                return True
        cur = parents.get(id(cur))
        hops += 1
    return False


def scan(py_file: Path) -> list[tuple[int, str]]:
    """Scan one python file for a test-path predicate function or a
    test-path pattern literal. Returns [(lineno, description), ...]."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    docstrings = _docstring_ids(tree)
    parents = _parent_map(tree)
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and re.match(r"_?is_test", node.name):
            violations.append((node.lineno, f"test-path predicate {node.name}()"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings \
                and any(t in node.value for t in _TOKENS) \
                and ("*" in node.value or "?" in node.value
                     or _in_pattern_call(node, parents)):
            violations.append((node.lineno, f"test-path pattern {node.value[:40]!r}"))
    return violations


def scan_tree(skills_dir: Path) -> dict[str, list[tuple[int, str]]]:
    """Scan every core/skills/*.py file except test_conventions.py (AC-12's
    own wording: "outside core/skills/test_conventions.py")."""
    out: dict[str, list[tuple[int, str]]] = {}
    for f in sorted(skills_dir.glob("*.py")):
        if f.name == "test_conventions.py":
            continue
        v = scan(f)
        if v:
            out[f.name] = v
    return out


def test_guard_green_on_shipped_tree():
    """AC-12: the scanner run over core/skills/*.py on the SHIPPED tree finds
    zero test-path predicates/patterns outside test_conventions.py — the
    copies in tdd_order, test_map, module_edges, file_roles and test-writer
    were removed or delegated."""
    violations = scan_tree(_SKILLS_DIR)
    assert violations == {}, violations


# ---------------------------------------------------------------------------
# Review round 2 (D-109-11, MEDIUM): EVERY consumer of is_test_path/
# test_signal outside test_conventions.py must pass exists= — the
# conservative default (D-109-9) silently starves a basename-only match for
# any caller that forgets to opt in, so a NEW consumer that copies an
# existing call site without exists= must fail this guard, not just degrade
# quietly. No allowlist.
# ---------------------------------------------------------------------------

_PREDICATE_NAMES = {"is_test_path", "test_signal"}


def _calls_missing_exists(py_file: Path) -> list[tuple[int, str]]:
    """[(lineno, call-source-ish), ...] for every is_test_path()/test_signal()
    call in *py_file* that has no exists= keyword argument."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if name not in _PREDICATE_NAMES:
            continue
        kw_names = {kw.arg for kw in node.keywords if kw.arg}
        if "exists" not in kw_names:
            # A **kwargs-forwarding call (no literal exists= at THIS call
            # site) is allowed only when it forwards a `**` dict — a bare
            # positional/keyword call with no exists= anywhere is a miss.
            if not any(kw.arg is None for kw in node.keywords):
                hits.append((node.lineno, f"{name}() with no exists="))
    return hits


def test_every_consumer_call_passes_exists():
    """MEDIUM (D-109-11): every is_test_path()/test_signal() call site in
    core/skills/*.py OUTSIDE test_conventions.py itself passes exists= — the
    ONE rule for ALL consumers the round-2 operator ruling requires. No
    allowlist: a future consumer that forgets to opt in fails this guard
    rather than silently inheriting the conservative (but possibly
    incomplete) default."""
    violations: dict[str, list[tuple[int, str]]] = {}
    for f in sorted(_SKILLS_DIR.glob("*.py")):
        if f.name == "test_conventions.py":
            continue
        hits = _calls_missing_exists(f)
        if hits:
            violations[f.name] = hits
    assert violations == {}, violations


def test_guard_detects_injected_violation_in_tmp_copy(tmp_path):
    """AC-12 fail-closed: a tmp_path copy of core/skills with ONE synthetic
    _is_test_path function injected into an unrelated module — the guard
    reports exactly that violation, proving the scanner bites rather than
    passing vacuously."""
    copy_dir = tmp_path / "core_skills_copy"
    shutil.copytree(_SKILLS_DIR, copy_dir)
    target = copy_dir / "settings.py"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(
            "\n\ndef _is_test_path(path):\n"
            "    return '__tests__' in path\n"
        )
    violations = scan_tree(copy_dir)
    assert "settings.py" in violations
    kinds = {desc for _, desc in violations["settings.py"]}
    assert any("_is_test_path" in k for k in kinds), violations
