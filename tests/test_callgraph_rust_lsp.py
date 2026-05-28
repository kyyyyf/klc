#!/usr/bin/env python3
"""Acceptance tests for KLC-001: Rust LSP call graph integration."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Test workspace fixture
TEST_WORKSPACE_FILES = {
    "Cargo.toml": """[package]
name = "test_workspace"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "test_workspace"
path = "src/main.rs"
""",
    "src/main.rs": """mod auth;
mod db;

fn register_user(username: &str, password: &str) {
    let hashed = auth::hash_password(password);
    db::insert_user(username, &hashed);
}

fn main() {
    register_user("alice", "secret123");
}
""",
    "src/auth.rs": """pub fn hash_password(password: &str) -> String {
    format!("hashed_{}", password)
}
""",
    "src/db.rs": """pub fn insert_user(username: &str, hashed_pw: &str) {
    println!("INSERT INTO users VALUES ('{}', '{}')", username, hashed_pw);
}
""",
}


def create_test_workspace(base_path: Path) -> Path:
    """Create test Rust workspace."""
    for file_path, content in TEST_WORKSPACE_FILES.items():
        full_path = base_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
    return base_path


def test_basic_edges():
    """AC-1: Test workspace with register_user → auth::hash_password, db::insert_user."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        
        output_file = workspace / "callgraph.json"
        
        # Run callgraph builder
        result = subprocess.run(
            [
                sys.executable,
                "core/skills/callgraph_rust_async.py",
                "--root", str(workspace),
                "--out", str(output_file),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}", file=sys.stderr)
            assert False, f"callgraph_rust_async.py failed with exit code {result.returncode}"
        
        # Load output
        with open(output_file) as f:
            data = json.load(f)
        
        symbols = data.get("symbols", {})
        
        # Verify register_user → auth::hash_password, db::insert_user
        register_user = symbols.get("src/main.rs::register_user")
        assert register_user is not None, "register_user not found in call graph"
        
        calls = register_user.get("calls", [])
        assert "src/auth.rs::hash_password" in calls, "register_user should call hash_password"
        assert "src/db.rs::insert_user" in calls, "register_user should call insert_user"
        
        # Verify called_by edges
        hash_password = symbols.get("src/auth.rs::hash_password")
        assert hash_password is not None, "hash_password not found in call graph"
        assert "src/main.rs::register_user" in hash_password.get("called_by", [])
        
        insert_user = symbols.get("src/db.rs::insert_user")
        assert insert_user is not None, "insert_user not found in call graph"
        assert "src/main.rs::register_user" in insert_user.get("called_by", [])
        
        print("✓ AC-1: Basic call edges validated")


def test_fallback_missing_analyzer():
    """AC-4: Graceful fallback when rust-analyzer not found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        create_test_workspace(workspace)
        
        output_file = workspace / "callgraph.json"
        
        # Run with invalid RUST_ANALYZER path
        env = os.environ.copy()
        env["RUST_ANALYZER"] = "/nonexistent/rust-analyzer"
        
        result = subprocess.run(
            [
                sys.executable,
                "core/skills/callgraph_rust_async.py",
                "--root", str(workspace),
                "--out", str(output_file),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        
        # Should exit with error code 1
        assert result.returncode == 1, "Should exit with error when rust-analyzer not found"
        
        # Should have clear error message
        assert "rust-analyzer not found" in result.stderr, "Should show clear error message"
        
        print("✓ AC-4: Graceful fallback validated")


if __name__ == "__main__":
    print("Running KLC-001 acceptance tests...")
    test_basic_edges()
    test_fallback_missing_analyzer()
    print("\nAll tests passed!")
