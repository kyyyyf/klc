"""KLC-139 step-4/step-5 — the AC-7 refusal ladder and the AC-8 empty file.

Shared by step-4 (the first 8 nodes: not-a-file, too-large, the combined
order case, the empty file, the symlink, and the Python half of the syntax
refusal) and step-5 (the remaining ast-grep-engine nodes). Every case asserts
the exact `SkeletonResult.text` (`<path>: <reason>\\n`) and `exit_code`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skeleton as sk  # noqa: E402
import tools as _tools  # noqa: E402


def _cfg(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".klc" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "settings.yml").write_text(body, encoding="utf-8")


def test_refusal_not_a_file(tmp_path, monkeypatch):
    """AC-7: a directory is refused `not a file: <path>`, exit 1."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    directory = tmp_path / "adir"
    directory.mkdir()
    result = sk.skeleton(str(directory))
    assert result.exit_code == 1
    assert result.text == f"{directory}: not a file: {directory}\n"


def test_refusal_file_too_large(tmp_path, monkeypatch):
    """AC-7: a file above `skeleton.max_bytes` is refused with the exact
    byte counts."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _cfg(tmp_path, "skeleton:\n  max_bytes: 100\n")
    big = tmp_path / "big.py"
    big.write_bytes(b"x" * 101)
    result = sk.skeleton(str(big))
    assert result.exit_code == 1
    assert result.text == (
        f"{big}: file too large (101 bytes > 100) — read with offset/limit\n"
    )


def test_refusal_order_directory_and_oversized_broken_file(tmp_path, monkeypatch):
    """AC-7: not-a-file is checked before too-large; too-large is checked
    before a Python syntax error."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _cfg(tmp_path, "skeleton:\n  max_bytes: 10\n")
    directory = tmp_path / "adir"
    directory.mkdir()
    result_dir = sk.skeleton(str(directory))
    assert "not a file" in result_dir.text

    broken = tmp_path / "broken.py"
    broken.write_bytes(b"def f(:\n" + b"x" * 20)
    result_broken = sk.skeleton(str(broken))
    assert "file too large" in result_broken.text
    assert "syntax errors" not in result_broken.text


@pytest.mark.parametrize("case", ["empty-py", "empty-ts", "empty-nosuffix"])
def test_empty_file_prints_no_symbols_before_astgrep_runs(tmp_path, monkeypatch, case):
    """AC-8: a 0-byte file of any suffix prints the header then
    `(no symbols)`, exit 0, decided before any ast-grep lookup — the
    monkeypatch makes any `tools.resolve_tool` call fail the test."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    def _boom(name):
        raise AssertionError("ast-grep must not be consulted for a 0-byte file")

    monkeypatch.setattr(_tools, "resolve_tool", _boom)
    name = {"empty-py": "empty.py", "empty-ts": "empty.ts",
            "empty-nosuffix": "emptyfile"}[case]
    fixture = tmp_path / name
    fixture.write_bytes(b"")
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 0
    if case == "empty-py":
        assert result.text == f"{fixture} (python, 0 lines)\n(no symbols)\n"
    else:
        assert result.text == f"{fixture} (0 lines)\n(no symbols)\n"


def test_symlink_resolved_before_size_check(tmp_path, monkeypatch):
    """AC-7: a symlink is resolved before the size check; the refusal names
    the link's own path, not the target's."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _cfg(tmp_path, "skeleton:\n  max_bytes: 10\n")
    big_target = tmp_path / "target_big.py"
    big_target.write_bytes(b"x" * 20)
    link = tmp_path / "link.py"
    link.symlink_to(big_target)
    result = sk.skeleton(str(link))
    assert result.exit_code == 1
    assert result.text == (
        f"{link}: file too large (20 bytes > 10) — read with offset/limit\n"
    )

    _cfg(tmp_path, "skeleton:\n  max_bytes: 1000\n")
    small_target = tmp_path / "target_small.py"
    small_target.write_text("def f():\n    pass\n", encoding="utf-8")
    small_link = tmp_path / "small_link.py"
    small_link.symlink_to(small_target)
    result_small = sk.skeleton(str(small_link))
    assert result_small.exit_code == 0
    assert "f() [1-2]" in result_small.text


@pytest.mark.parametrize("case", ["python", "astgrep"])
def test_refusal_syntax_errors(tmp_path, monkeypatch, case):
    """AC-7: a Python syntax error (step-4) or an ast-grep `kind: ERROR`
    match (step-5) is refused `syntax errors — read the file instead`,
    exit 1."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    if case == "python":
        broken = tmp_path / "broken.py"
        broken.write_text("def f(:\n    pass\n", encoding="utf-8")
    else:
        broken = tmp_path / "broken.ts"
        broken.write_text("export function broken( {\n", encoding="utf-8")
    result = sk.skeleton(str(broken))
    assert result.exit_code == 1
    assert result.text == f"{broken}: syntax errors — read the file instead\n"


def test_refusal_astgrep_unavailable_fail_closed(tmp_path, monkeypatch):
    """AC-7: a missing ast-grep tool is a refusal, not a silent regex
    fallback (no-fallback assumption)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(_tools, "resolve_tool", lambda name: None)
    fixture = tmp_path / "a.ts"
    fixture.write_text("export function ok() {}\n", encoding="utf-8")
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 1
    assert result.text == f"{fixture}: ast-grep unavailable — read the file instead\n"


def _write_stub(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "stub-ast-grep.sh"
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)
    return stub


@pytest.mark.parametrize("kind", ["nonzero-exit", "no-inspect-line"])
def test_refusal_astgrep_failed(tmp_path, monkeypatch, kind):
    """AC-7: a stub ast-grep that exits non-zero, or that prints valid JSON
    with no `--inspect` sentinel line, is `ast-grep failed`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    if kind == "nonzero-exit":
        stub = _write_stub(tmp_path, "#!/usr/bin/env bash\nexit 2\n")
        expected = "ast-grep failed (exit 2) — read the file instead"
    else:
        stub = _write_stub(tmp_path, "#!/usr/bin/env bash\necho '[]'\nexit 0\n")
        expected = "ast-grep failed (no inspect output) — read the file instead"
    monkeypatch.setattr(_tools, "resolve_tool", lambda name: stub)
    fixture = tmp_path / "a.ts"
    fixture.write_text("export function ok() {}\n", encoding="utf-8")
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 1
    assert result.text == f"{fixture}: {expected}\n"


@pytest.mark.parametrize("case", ["go", "unknown-ext"])
def test_refusal_unsupported_language(tmp_path, monkeypatch, case):
    """AC-7: a real generic-profile scan that finds no applied rule
    (`appliedRuleCount=0`, Go) or no `entity|file` line at all (an unknown
    extension) is `unsupported language`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    if case == "go":
        fixture = tmp_path / "main.go"
        fixture.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
        expected_ext = ".go"
    else:
        fixture = tmp_path / "a.xyz"
        fixture.write_text("hello\n", encoding="utf-8")
        expected_ext = ".xyz"
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 1
    assert result.text == f"{fixture}: unsupported language: {expected_ext}\n"


def test_refusal_no_extension_python_shebang_still_unsupported(tmp_path, monkeypatch):
    """AC-7/Q-007: an extensionless Python-shebang file (the real
    `scripts/klc`, read-only per D-210) is dispatched by suffix only, so it
    is `unsupported language: (no extension)`, never run through `ast`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    real_klc = REPO / "scripts" / "klc"
    result = sk.skeleton(str(real_klc))
    assert result.exit_code == 1
    assert result.text == f"{real_klc}: unsupported language: (no extension)\n"


def test_valid_file_with_no_entries_prints_no_symbols(monkeypatch):
    """AC-8: a supported file that parses cleanly but yields no rule matches
    prints the header then `(no symbols)`, exit 0."""
    # A short tmp root (unlike pytest's nested tmp_path), so the 62-char
    # `rule-scoped` header suffix does not spuriously truncate an otherwise
    # short path.
    with tempfile.TemporaryDirectory(prefix="k139-") as root:
        monkeypatch.setenv("PROJECT_ROOT", root)
        fixture = Path(root) / "hidden_only.ts"
        fixture.write_text("function hidden() {}\nconst x = 1;\n", encoding="utf-8")
        result = sk.skeleton(str(fixture))
    assert result.exit_code == 0
    assert result.text == (
        f"{fixture} (typescript, rule-scoped: only what the profile's rules match)\n"
        "(no symbols)\n"
    )
