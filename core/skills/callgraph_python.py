#!/usr/bin/env python3
"""callgraph_python.py — build function-level call graph for Python code.

Phase 4.1: generates index/callgraph/python.json with caller/callee relationships.

Usage:
    callgraph_python.py --root <path> --out <path> [--module <name>]

Output (JSON):
    {
      "symbols": {
        "src/api/users.py::create_user": {
          "kind": "function",
          "file": "src/api/users.py",
          "line": 42,
          "calls": ["src/db/users.py::insert", "src/auth/jwt.py::sign"],
          "called_by": []
        }
      }
    }

Symbol naming:
- Module-level function: <file>::<name>
- Class method: <file>::<ClassName>.<method_name>
- Nested function: <file>::<outer>.<inner>

Resolution strategy:
- Import-aware: tracks `from X import Y`, `import X as Y`
- Resolves qualified calls (`module.func`) via import map
- Best-effort for dynamic dispatch, getattr, decorators

Limitations:
- Does not resolve: getattr(obj, method_name)(), decorators wrapping calls,
  exec/eval, __import__, plugin systems
- Class inheritance: tracks calls to methods defined in same file only
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.shared.paths import framework_root  # noqa: E402


class Symbol:
    """Represents a callable symbol in the codebase."""
    def __init__(self, qualified_name: str, kind: str, file: str, line: int):
        self.qualified_name = qualified_name
        self.kind = kind  # "function", "method", "lambda"
        self.file = file
        self.line = line
        self.calls: set[str] = set()
        self.called_by: set[str] = set()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "calls": sorted(self.calls),
            "called_by": sorted(self.called_by),
        }


class ImportResolver:
    """Tracks imports for a single file."""
    def __init__(self, file_path: str):
        self.file_path = file_path
        # Local name → (module_path, original_name)
        self.imports: dict[str, tuple[str, str]] = {}
        # module alias → module_path
        self.module_aliases: dict[str, str] = {}

    def add_import_from(self, module: str, name: str, asname: str | None):
        """from <module> import <name> [as <asname>]"""
        local_name = asname or name
        self.imports[local_name] = (module, name)

    def add_import(self, module: str, asname: str | None):
        """import <module> [as <asname>]"""
        local_name = asname or module
        self.module_aliases[local_name] = module

    def resolve_call(self, call_node: ast.expr, root: Path) -> str | None:
        """Resolve a Call node to a qualified symbol name.

        Returns:
            "path/to/file.py::symbol" or None if unresolvable.
        """
        if isinstance(call_node, ast.Name):
            # Direct call: func()
            name = call_node.id
            if name in self.imports:
                module_path, original_name = self.imports[name]
                file_path = self._module_to_file(module_path, root)
                if file_path:
                    return f"{file_path}::{original_name}"
            # Could be local — caller handles this
            return None

        elif isinstance(call_node, ast.Attribute):
            # Qualified call: obj.method() or module.func()
            if isinstance(call_node.value, ast.Name):
                obj_name = call_node.value.id
                attr_name = call_node.attr

                # Check if obj_name is a module alias
                if obj_name in self.module_aliases:
                    module_path = self.module_aliases[obj_name]
                    file_path = self._module_to_file(module_path, root)
                    if file_path:
                        return f"{file_path}::{attr_name}"

                # Check if obj_name is an imported class/object
                if obj_name in self.imports:
                    module_path, original_name = self.imports[obj_name]
                    file_path = self._module_to_file(module_path, root)
                    if file_path:
                        return f"{file_path}::{original_name}.{attr_name}"

            # Nested attribute: a.b.c() — skip for now
            return None

        return None

    def _module_to_file(self, module_path: str, root: Path) -> str | None:
        """Convert module path (e.g., 'src.api.users') to file path relative to root.

        Returns:
            "src/api/users.py" or None if not found.
        """
        # First, check if it's a sibling module (same directory as current file)
        # This handles cases like `from core.shared.paths import framework_root` in core/skills/
        current_dir = Path(self.file_path).parent
        sibling = root / current_dir / f"{module_path}.py"
        if sibling.exists():
            return str(sibling.relative_to(root))

        # Try as package
        parts = module_path.split(".")
        candidate = root / "/".join(parts) / "__init__.py"
        if candidate.exists():
            return str(candidate.relative_to(root))

        # Try as module
        if len(parts) > 1:
            candidate = root / "/".join(parts[:-1]) / f"{parts[-1]}.py"
        else:
            candidate = root / f"{parts[0]}.py"
        if candidate.exists():
            return str(candidate.relative_to(root))

        # External module (not in this codebase)
        return None


class CallGraphBuilder(ast.NodeVisitor):
    """Builds call graph from a single Python file."""
    def __init__(self, file_path: str, root: Path, module_name: str | None):
        self.file_path = file_path
        self.root = root
        self.module_name = module_name
        self.resolver = ImportResolver(file_path)
        self.symbols: dict[str, Symbol] = {}
        self.current_scope: list[str] = []  # Stack of enclosing function/class names
        self.current_symbol: str | None = None

    def visit_Import(self, node: ast.Import):
        """import X [as Y]"""
        for alias in node.names:
            self.resolver.add_import(alias.name, alias.asname)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """from X import Y [as Z]"""
        if node.module:
            for alias in node.names:
                self.resolver.add_import_from(node.module, alias.name, alias.asname)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Function or method definition."""
        self._visit_callable(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Async function definition."""
        self._visit_callable(node, "function")

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str):
        """Common handler for function/method definitions."""
        # Build qualified name
        if self.current_scope:
            qualified = f"{self.file_path}::{'.'.join(self.current_scope)}.{node.name}"
        else:
            qualified = f"{self.file_path}::{node.name}"

        # Detect if this is a method (inside a class)
        if self.current_scope and kind == "function":
            # Check if parent scope is a class
            parent_kind = self._scope_kind(self.current_scope[-1])
            if parent_kind == "class":
                kind = "method"

        symbol = Symbol(qualified, kind, self.file_path, node.lineno)
        self.symbols[qualified] = symbol

        # Enter scope
        prev_symbol = self.current_symbol
        self.current_symbol = qualified
        self.current_scope.append(node.name)

        # Visit body
        for stmt in node.body:
            self.visit(stmt)

        # Exit scope
        self.current_scope.pop()
        self.current_symbol = prev_symbol

    def visit_ClassDef(self, node: ast.ClassDef):
        """Class definition."""
        self.current_scope.append(node.name)
        self.generic_visit(node)
        self.current_scope.pop()

    def visit_Call(self, node: ast.Call):
        """Function/method call."""
        if not self.current_symbol:
            # Top-level call outside any function — skip
            self.generic_visit(node)
            return

        # Try to resolve the callee
        callee = self.resolver.resolve_call(node.func, self.root)

        if not callee:
            # Maybe it's a local function call in the same file
            if isinstance(node.func, ast.Name):
                local_name = node.func.id
                # Check if it's a known symbol in this file
                candidate = f"{self.file_path}::{local_name}"
                if candidate in self.symbols:
                    callee = candidate
                else:
                    # Could be a builtin or unresolved import
                    pass

        if callee:
            # Record the call edge
            caller = self.symbols[self.current_symbol]
            caller.calls.add(callee)

        self.generic_visit(node)

    def _scope_kind(self, scope_name: str) -> str:
        """Heuristic: determine if a scope name is a class (capitalized) or function."""
        return "class" if scope_name[0].isupper() else "function"


def collect_python_files(root: Path, module_name: str | None) -> list[Path]:
    """Find all .py files under root (or specific module if given)."""
    if module_name:
        # Scan only the specified module
        module_dir = root / module_name.replace(".", "/")
        if not module_dir.exists():
            sys.stderr.write(f"callgraph_python: module {module_name} not found\n")
            return []
        search_root = module_dir
    else:
        search_root = root

    files: list[Path] = []
    for path in search_root.rglob("*.py"):
        if path.is_file():
            files.append(path)
    return files


def build_call_graph(root: Path, module_name: str | None) -> dict[str, Symbol]:
    """Build call graph for all Python files under root."""
    files = collect_python_files(root, module_name)
    all_symbols: dict[str, Symbol] = {}

    for file_path in files:
        rel_path = str(file_path.relative_to(root))
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
            builder = CallGraphBuilder(rel_path, root, module_name)
            builder.visit(tree)
            all_symbols.update(builder.symbols)
        except SyntaxError as e:
            sys.stderr.write(f"callgraph_python: syntax error in {rel_path}: {e}\n")
        except Exception as e:
            sys.stderr.write(f"callgraph_python: error parsing {rel_path}: {e}\n")

    return all_symbols


def compute_called_by(symbols: dict[str, Symbol]):
    """Populate called_by edges based on calls edges."""
    for caller_name, caller in symbols.items():
        for callee_name in caller.calls:
            if callee_name in symbols:
                symbols[callee_name].called_by.add(caller_name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Root directory to scan")
    ap.add_argument("--out", required=True, help="Output JSON file path")
    ap.add_argument("--module", help="Optional: scan only this module (e.g., 'src.api')")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        sys.stderr.write(f"callgraph_python: root not found: {root}\n")
        return 1

    symbols = build_call_graph(root, args.module)
    compute_called_by(symbols)

    # Convert to output format
    output = {"symbols": {name: sym.to_dict() for name, sym in symbols.items()}}

    # Write to file
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(f"callgraph_python: indexed {len(symbols)} symbols → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
