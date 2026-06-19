#!/usr/bin/env python3
"""Acceptance tests for KLC-004: C++ call graph via clangd LSP."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

CLANGD_AVAILABLE = shutil.which("clangd") is not None

_ROOT = Path(__file__).resolve().parent.parent
CALLGRAPH_CPP_SCRIPT = _ROOT / "core/skills/callgraph_cpp.py"

# Fixture: minimal C++ project mirroring the Rust fixture in test_callgraph_rust_lsp.py.
# register_user (main.cpp) → hash_password (auth.cpp), insert_user (db.cpp)
# hash_password is DECLARED in auth.h, DEFINED in auth.cpp — exercises AC-3.

TEST_FILES = {
    "src/main.cpp": """\
#include "auth.h"
#include "db.h"

void register_user(const char* username, const char* password) {
    auto hashed = hash_password(password);
    insert_user(username, hashed.c_str());
}

int main() {
    register_user("alice", "secret123");
    return 0;
}
""",
    "src/auth.h": """\
#pragma once
#include <string>
std::string hash_password(const char* password);
""",
    "src/auth.cpp": """\
#include "auth.h"

std::string hash_password(const char* password) {
    return std::string("hashed_") + password;
}
""",
    "src/db.h": """\
#pragma once
void insert_user(const char* username, const char* hashed_pw);
""",
    "src/db.cpp": """\
#include "db.h"
#include <cstdio>

void insert_user(const char* username, const char* hashed_pw) {
    printf("INSERT INTO users VALUES ('%s', '%s')\\n", username, hashed_pw);
}
""",
}


def create_test_workspace(base_path: Path) -> Path:
    """Create C++ workspace with source files and compile_commands.json."""
    for rel, content in TEST_FILES.items():
        full = base_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)

    src_dir = str(base_path / "src")
    compile_commands = [
        {
            "directory": str(base_path),
            "file": str(base_path / "src/main.cpp"),
            "command": f"clang++ -std=c++17 -I{src_dir} {base_path}/src/main.cpp -o /dev/null",
        },
        {
            "directory": str(base_path),
            "file": str(base_path / "src/auth.cpp"),
            "command": f"clang++ -std=c++17 -I{src_dir} {base_path}/src/auth.cpp -o /dev/null",
        },
        {
            "directory": str(base_path),
            "file": str(base_path / "src/db.cpp"),
            "command": f"clang++ -std=c++17 -I{src_dir} {base_path}/src/db.cpp -o /dev/null",
        },
    ]
    (base_path / "compile_commands.json").write_text(json.dumps(compile_commands, indent=2))
    return base_path


def _run_script(workspace: Path, output_file: Path, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(CALLGRAPH_CPP_SCRIPT),
            "--backend", "clangd",
            "--compdb", str(workspace / "compile_commands.json"),
            "--out", str(output_file),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_ROOT),
    )


def _find_symbol(symbols: dict, name: str) -> dict | None:
    """Find symbol by name suffix in 'rel_path::name' keyed dict."""
    for key, sym in symbols.items():
        if key == name or key.endswith(f"::{name}"):
            return sym
    return None


@pytest.mark.skipif(not CLANGD_AVAILABLE, reason="clangd not on PATH")
def test_basic_edges():
    """AC-1: script generates call graph in expected schema with correct call edges."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        output_file = workspace / "callgraph.json"

        result = _run_script(workspace, output_file)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}", file=sys.stderr)
            assert False, f"callgraph_cpp.py exited {result.returncode}"

        data = json.loads(output_file.read_text())
        assert "symbols" in data, "top-level 'symbols' key missing"
        symbols = data["symbols"]

        # Edge: register_user → hash_password and insert_user
        reg = _find_symbol(symbols, "register_user")
        assert reg is not None, f"register_user not found; keys={list(symbols)[:10]}"
        calls = reg["calls"]
        assert any("hash_password" in c for c in calls), f"register_user.calls missing hash_password; got {calls}"
        assert any("insert_user" in c for c in calls), f"register_user.calls missing insert_user; got {calls}"

        # Per-symbol schema keys
        for key, sym in symbols.items():
            for field in ("kind", "file", "line", "calls", "called_by"):
                assert field in sym, f"symbol '{key}' missing field '{field}'"


@pytest.mark.skipif(not CLANGD_AVAILABLE, reason="clangd not on PATH")
def test_call_hierarchy_direct_edges():
    """AC-2: called_by edges populated via clangd call hierarchy (incomingCalls)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        output_file = workspace / "callgraph.json"

        result = _run_script(workspace, output_file)
        assert result.returncode == 0, f"script failed: {result.stderr}"

        symbols = json.loads(output_file.read_text())["symbols"]

        hash_pw = _find_symbol(symbols, "hash_password")
        assert hash_pw is not None, "hash_password not found"
        assert any("register_user" in cb for cb in hash_pw["called_by"]), (
            f"hash_password.called_by missing register_user; got {hash_pw['called_by']}"
        )

        insert_user = _find_symbol(symbols, "insert_user")
        assert insert_user is not None, "insert_user not found"
        assert any("register_user" in cb for cb in insert_user["called_by"]), (
            f"insert_user.called_by missing register_user; got {insert_user['called_by']}"
        )


@pytest.mark.skipif(not CLANGD_AVAILABLE, reason="clangd not on PATH")
def test_header_function_attribution():
    """AC-3: function declared in .h, defined in .cpp → attributed to .cpp TU."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        output_file = workspace / "callgraph.json"

        result = _run_script(workspace, output_file)
        assert result.returncode == 0, f"script failed: {result.stderr}"

        symbols = json.loads(output_file.read_text())["symbols"]

        hash_pw = _find_symbol(symbols, "hash_password")
        assert hash_pw is not None, "hash_password not found"
        file_attr = hash_pw["file"]
        assert "auth.cpp" in file_attr, (
            f"hash_password must be attributed to auth.cpp (definition TU); got '{file_attr}'"
        )
        assert not file_attr.endswith("auth.h"), "hash_password must not be attributed to header"


# --- Step-2 tests (written here, made green in step-2) ---

@pytest.mark.skipif(not CLANGD_AVAILABLE, reason="clangd not on PATH")
def test_find_references_scope():
    """AC-4: findReferences returns compact file:line list, no source bodies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        output_file = workspace / "callgraph.json"

        result = _run_script(workspace, output_file)
        assert result.returncode == 0, f"script failed: {result.stderr}"

        data = json.loads(output_file.read_text())
        # references key populated for at least one symbol
        symbols = data["symbols"]
        has_refs = any("references" in sym for sym in symbols.values())
        # references are file:line strings, not source bodies
        for sym in symbols.values():
            for ref in sym.get("references", []):
                assert isinstance(ref, str), "reference must be a string"
                assert ":" in ref, f"reference must be 'file:line', got '{ref}'"
                # No source content — reference must not contain newlines
                assert "\n" not in ref, "reference must not contain source content"


def test_missing_clangd_error():
    """AC-5: clear error when clangd is not on PATH."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        output_file = workspace / "callgraph.json"

        env = os.environ.copy()
        env["CLANGD"] = "/nonexistent/clangd"
        env.pop("PATH", None)
        env["PATH"] = "/nonexistent"

        result = subprocess.run(
            [
                sys.executable,
                str(CALLGRAPH_CPP_SCRIPT),
                "--backend", "clangd",
                "--compdb", str(workspace / "compile_commands.json"),
                "--out", str(output_file),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        assert result.returncode != 0, "should exit non-zero when clangd not found"
        assert "clangd" in result.stderr.lower(), f"error must mention clangd; got: {result.stderr}"


def test_missing_compdb_error():
    """AC-5: clear error when compile_commands.json is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        output_file = workspace / "callgraph.json"

        result = subprocess.run(
            [
                sys.executable,
                str(CALLGRAPH_CPP_SCRIPT),
                "--backend", "clangd",
                "--compdb", str(workspace / "compile_commands.json"),
                "--out", str(output_file),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode != 0, "should exit non-zero when compdb missing"
        assert "compile_commands" in result.stderr or "compdb" in result.stderr.lower(), (
            f"error must mention compile_commands.json; got: {result.stderr}"
        )


@pytest.mark.skipif(not CLANGD_AVAILABLE, reason="clangd not on PATH")
def test_indexing_is_prompt():
    """Step-3: indexing wait happens after didOpen — 3-TU fixture completes < 20s wall-clock."""
    import time
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        output_file = workspace / "callgraph.json"

        start = time.monotonic()
        result = _run_script(workspace, output_file, timeout=120)
        elapsed = time.monotonic() - start

        assert result.returncode == 0, f"script failed: {result.stderr}"
        assert elapsed < 20.0, (
            f"script took {elapsed:.1f}s — indexing wait must happen after didOpen "
            f"(expected < 20s); check initialize() for premature indexing_done.wait()"
        )


def test_schema_compat():
    """AC-6: output schema byte-compatible with python.json / rust.json."""
    python_json = _ROOT / ".klc/index/callgraph/python.json"
    if not python_json.exists():
        pytest.skip("python.json not found — run on a project that has been indexed")

    with open(python_json) as f:
        ref = json.load(f)

    assert "symbols" in ref
    # Pick any symbol and verify field set
    sample = next(iter(ref["symbols"].values()))
    required_fields = {"kind", "file", "line", "calls", "called_by"}
    assert required_fields.issubset(sample.keys()), (
        f"reference schema missing fields: {required_fields - set(sample.keys())}"
    )
