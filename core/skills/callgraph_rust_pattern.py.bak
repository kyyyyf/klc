#!/usr/bin/env python3
"""callgraph_rust.py — build function-level call graph for Rust code (pattern-based).

Phase 4.2: generates index/callgraph/rust.json with caller/callee relationships.

Usage:
    callgraph_rust.py --root <path> --out <path>

Output (JSON):
    {
      "symbols": {
        "src/lib.rs::create_user": {
          "kind": "function",
          "file": "src/lib.rs",
          "line": 42,
          "calls": ["src/db.rs::insert", "src/auth.rs::sign_token"],
          "called_by": []
        }
      }
    }

Symbol naming:
- Free function: <file>::<name>
- Method: <file>::<Struct>::<method>
- Trait method: <file>::<Trait>::<method>

Resolution strategy:
- Pattern-based parsing of fn definitions and function calls
- use/mod imports tracked for cross-file resolution
- Best-effort: does not handle macros, trait objects, or complex generics

Limitations:
- LSP integration deferred (rust-analyzer requires complex async handling + workspace indexing)
- Current version uses regex + simple parsing for MVP
- Trait dispatch: resolves to trait definition only (not impls)
- Macro-generated code: not resolved
- Method calls on trait objects: not resolved

Future: full rust-analyzer LSP integration for production use.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import framework_root  # noqa: E402


class Symbol:
    """Represents a callable symbol."""
    def __init__(self, qualified_name: str, kind: str, file: str, line: int):
        self.qualified_name = qualified_name
        self.kind = kind  # "function", "method"
        self.file = file
        self.line = line
        self.calls: set[str] = set()
        self.called_by: set[str] = set()

    def to_dict(self):
        return {
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "calls": sorted(self.calls),
            "called_by": sorted(self.called_by),
        }


def collect_rust_files(root: Path) -> list[Path]:
    """Find all .rs files (excluding target/)."""
    files: list[Path] = []
    for path in root.rglob("*.rs"):
        if "/target/" in str(path) or "/.cargo/" in str(path):
            continue
        if path.is_file():
            files.append(path)
    return files


def parse_rust_file(file_path: Path, root: Path) -> tuple[dict[str, Symbol], dict[str, str]]:
    """Parse a Rust file to extract function definitions and imports.

    Returns:
        (symbols_map, imports_map)
        symbols_map: {qualified_name: Symbol}
        imports_map: {local_name: module_path}
    """
    rel_path = str(file_path.relative_to(root))
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    symbols_map: dict[str, Symbol] = {}
    imports_map: dict[str, str] = {}

    # Parse use statements: use crate::module::function;
    use_pattern = re.compile(r'^\s*use\s+([\w:]+)(?:\s+as\s+(\w+))?;')

    # Parse fn definitions: pub fn name(...) or fn name(...)
    # Also handle: impl Struct { fn method(...) }
    fn_pattern = re.compile(r'^\s*(?:pub\s+)?fn\s+(\w+)\s*\(')
    impl_pattern = re.compile(r'^\s*impl(?:<[^>]+>)?\s+(\w+)(?:\s+for\s+(\w+))?\s*\{')

    current_impl: str | None = None  # Track current impl block

    for line_num, line in enumerate(lines, start=1):
        # Track use statements
        use_match = use_pattern.match(line)
        if use_match:
            module_path = use_match.group(1)
            alias = use_match.group(2)
            # Extract last component as the imported name
            parts = module_path.split("::")
            name = alias or parts[-1]
            imports_map[name] = module_path
            continue

        # Track impl blocks
        impl_match = impl_pattern.match(line)
        if impl_match:
            struct_name = impl_match.group(1)
            current_impl = struct_name
            continue

        # Track end of impl block (closing brace at start of line)
        if current_impl and re.match(r'^\s*\}\s*$', line):
            current_impl = None
            continue

        # Track fn definitions
        fn_match = fn_pattern.match(line)
        if fn_match:
            fn_name = fn_match.group(1)
            if current_impl:
                qualified = f"{rel_path}::{current_impl}::{fn_name}"
                kind = "method"
            else:
                qualified = f"{rel_path}::{fn_name}"
                kind = "function"

            symbols_map[qualified] = Symbol(qualified, kind, rel_path, line_num)

    return symbols_map, imports_map


def extract_function_calls(file_path: Path, root: Path, symbols_map: dict[str, Symbol], imports_map: dict[str, str]):
    """Parse function calls in a Rust file and populate symbols_map[].calls."""
    rel_path = str(file_path.relative_to(root))
    text = file_path.read_text(encoding="utf-8", errors="ignore")

    # Find all symbols defined in this file
    local_symbols = {name: sym for name, sym in symbols_map.items() if sym.file == rel_path}

    # Pattern: function_name(...) or module::function_name(...) — captures function calls
    call_pattern = re.compile(r'\b([\w:]+)\s*\(')

    # Track which function we're currently inside
    current_function: str | None = None
    brace_depth = 0

    for line in text.splitlines():
        # Track function entry
        fn_match = re.search(r'\bfn\s+(\w+)\s*\(', line)
        if fn_match:
            fn_name = fn_match.group(1)
            # Find the symbol for this function
            for qual_name, sym in local_symbols.items():
                if qual_name.endswith(f"::{fn_name}"):
                    current_function = qual_name
                    brace_depth = 0
                    break

        # Track brace depth (approximate — doesn't handle strings/comments perfectly)
        brace_depth += line.count("{") - line.count("}")

        # If we've closed all braces, exit current function
        if brace_depth <= 0:
            current_function = None

        # Extract function calls (skip if this is the fn definition line)
        if current_function and not fn_match:
            for match in call_pattern.finditer(line):
                callee_name = match.group(1)

                # Handle qualified calls: module::function
                if "::" in callee_name:
                    parts = callee_name.split("::")
                    module = parts[0]
                    func = parts[-1]

                    # Check if module is an imported module
                    if module in imports_map:
                        module_path = imports_map[module]
                        resolved_file = resolve_module_to_file(module_path, root)
                        if resolved_file:
                            resolved_qual = f"{resolved_file}::{func}"
                            symbols_map[current_function].calls.add(resolved_qual)
                            continue

                    # Otherwise try to resolve as crate module (e.g., auth::func)
                    # Assume it's in src/<module>.rs
                    candidate_file = root / "src" / f"{module}.rs"
                    if candidate_file.exists():
                        try:
                            resolved_file = str(candidate_file.relative_to(root))
                            resolved_qual = f"{resolved_file}::{func}"
                            symbols_map[current_function].calls.add(resolved_qual)
                            continue
                        except ValueError:
                            pass

                # Check if it's a local symbol (simple name)
                local_match = None
                for qual_name in local_symbols.keys():
                    if qual_name.endswith(f"::{callee_name}"):
                        local_match = qual_name
                        break

                if local_match:
                    symbols_map[current_function].calls.add(local_match)
                    continue

                # Check if it's an imported symbol
                if callee_name in imports_map:
                    module_path = imports_map[callee_name]
                    # Try to resolve module path to file
                    resolved_file = resolve_module_to_file(module_path, root)
                    if resolved_file:
                        resolved_qual = f"{resolved_file}::{callee_name}"
                        symbols_map[current_function].calls.add(resolved_qual)


def resolve_module_to_file(module_path: str, root: Path) -> str | None:
    """Resolve crate::module::submodule to a file path.

    Examples:
        crate::auth -> src/auth.rs or src/auth/mod.rs
        super::db -> (relative, skip for now)
    """
    if module_path.startswith("crate::"):
        parts = module_path[7:].split("::")
    elif module_path.startswith("super::") or module_path.startswith("self::"):
        # Relative imports — too complex for simple parser
        return None
    else:
        # Absolute path (external crate)
        return None

    # Try src/module.rs
    candidate = root / "src" / "/".join(parts[:-1]) / f"{parts[-1]}.rs"
    if candidate.exists():
        try:
            return str(candidate.relative_to(root))
        except ValueError:
            return None

    # Try src/module/mod.rs
    candidate = root / "src" / "/".join(parts) / "mod.rs"
    if candidate.exists():
        try:
            return str(candidate.relative_to(root))
        except ValueError:
            return None

    return None


def compute_called_by(symbols_map: dict[str, Symbol]):
    """Populate called_by edges based on calls."""
    for caller_name, caller in symbols_map.items():
        for callee_name in caller.calls:
            if callee_name in symbols_map:
                symbols_map[callee_name].called_by.add(caller_name)


def build_call_graph(root: Path) -> dict[str, Symbol]:
    """Build call graph for Rust workspace."""
    files = collect_rust_files(root)
    sys.stderr.write(f"callgraph_rust: found {len(files)} .rs files\n")

    all_symbols: dict[str, Symbol] = {}
    all_imports: dict[Path, dict[str, str]] = {}

    # Phase 1: extract all function definitions and imports
    for file_path in files:
        try:
            symbols, imports = parse_rust_file(file_path, root)
            all_symbols.update(symbols)
            all_imports[file_path] = imports
        except Exception as e:
            rel_path = file_path.relative_to(root)
            sys.stderr.write(f"callgraph_rust: error parsing {rel_path}: {e}\n")

    sys.stderr.write(f"callgraph_rust: extracted {len(all_symbols)} function definitions\n")

    # Phase 2: extract function calls and resolve
    for file_path in files:
        try:
            imports = all_imports.get(file_path, {})
            extract_function_calls(file_path, root, all_symbols, imports)
        except Exception as e:
            rel_path = file_path.relative_to(root)
            sys.stderr.write(f"callgraph_rust: error extracting calls from {rel_path}: {e}\n")

    # Phase 3: compute called_by edges
    compute_called_by(all_symbols)

    return all_symbols


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Root directory (Cargo workspace)")
    ap.add_argument("--out", required=True, help="Output JSON file path")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        sys.stderr.write(f"callgraph_rust: root not found: {root}\n")
        return 1

    # Check for Cargo.toml (advisory, not required)
    cargo_toml = root / "Cargo.toml"
    if not cargo_toml.exists():
        sys.stderr.write(f"callgraph_rust: warning: no Cargo.toml at {root}\n")

    symbols = build_call_graph(root)

    # Write output
    output = {"symbols": {name: sym.to_dict() for name, sym in symbols.items()}}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(f"callgraph_rust: indexed {len(symbols)} symbols → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
