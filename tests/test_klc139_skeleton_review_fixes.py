"""KLC-139 step-8 — review round 1 fixes (code-review + external-review).

Every AC-7 refusal must stay exactly one line, never a traceback, never an
empty body. This file pins the seven findings from
`.klc/tickets/KLC-139/review/code-review-findings.json` and
`review/external-review-findings.json`:

1. (HIGH) a UTF-8-BOM `.py` file was refused as "syntax errors".
2. (HIGH) a `RecursionError` from `ast.parse` on a deeply nested but valid
   file escaped as a traceback.
3. (MEDIUM) an unreadable file (`PermissionError`/`OSError`) crashed instead
   of refusing.
4. (MEDIUM) a non-UTF-8 non-Python file that ast-grep skips was dishonestly
   reported "unsupported language"; a path containing a newline broke the
   `--inspect` stderr parser the same way.
5. (LOW) the header's line count used `str.splitlines()`, which disagrees
   with `ast`'s own line breaks (form feed, U+2028, ...).
6. (LOW) the ast-grep subprocess decoded with the locale encoding
   (`text=True`, no `encoding=`) instead of a fixed UTF-8/replace codec.
7. (LOW) `klc skeleton -- -x.ts` (the standard `--` separator) was rejected.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
KLC = REPO / "scripts" / "klc"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skeleton as sk  # noqa: E402
import tools  # noqa: E402


def _astgrep_or_skip() -> None:
    if not tools.resolve_tool("ast-grep"):
        pytest.skip("ast-grep not installed in this environment")


def test_bom_prefixed_python_file_gives_outline_not_syntax_error(tmp_path, monkeypatch):
    """AC-3 (HIGH #1): a UTF-8-BOM-prefixed .py file, which `python3` itself
    runs fine, gives a normal outline (exit 0), not a false 'syntax errors'
    refusal."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "bom.py"
    fixture.write_bytes(b"\xef\xbb\xbfimport os\ndef f():\n    pass\n")
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 0, result.text
    assert "syntax errors" not in result.text
    assert "f() [2-3]" in result.text


def test_deeply_nested_expression_refused_not_traceback(tmp_path, monkeypatch):
    """AC-7 (HIGH #2): a syntactically VALID but deeply nested expression
    (well under skeleton.max_bytes) makes `ast.parse` raise `RecursionError`
    in CPython's own parser; this must become one refusal line, never a
    traceback with an empty stdout."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    body = "x = " + "+".join(["1"] * 50_000) + "\n"
    fixture = tmp_path / "deep.py"
    fixture.write_text(body, encoding="utf-8")
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 1
    assert result.text == f"{fixture}: too deeply nested to parse — read the file instead\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permission bits")
def test_unreadable_file_refused_not_traceback(tmp_path, monkeypatch):
    """AC-7 (MEDIUM #3): a chmod-000 file (readable stat, unreadable
    content — `is_file()`/`stat()` succeed, only the actual read fails) is
    refused with one honest line, not a PermissionError traceback."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "noperm.py"
    fixture.write_text("def f():\n    pass\n", encoding="utf-8")
    fixture.chmod(0o000)
    try:
        result = sk.skeleton(str(fixture))
    finally:
        fixture.chmod(0o644)
    assert result.exit_code == 1
    assert result.text.startswith(f"{fixture}: cannot read file:")
    assert "Traceback" not in result.text


def test_non_utf8_nonpython_file_honest_reason_not_unsupported_language(tmp_path, monkeypatch):
    """AC-7 (MEDIUM #4): a non-UTF-8 .ts file, fully covered by the generic
    profile, must not be reported 'unsupported language' (ast-grep silently
    skips files it cannot decode, which is a dishonest signal for a
    coverage gap that does not exist)."""
    _astgrep_or_skip()
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "nonutf8.ts"
    fixture.write_bytes(b"export function ok() { return \xe9; }\n")
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 1
    assert "unsupported language" not in result.text
    assert result.text == f"{fixture}: not valid UTF-8 — read the file instead\n"


def test_path_with_newline_does_not_produce_false_reason(tmp_path, monkeypatch):
    """AC-7 (MEDIUM #4, the newline-in-path half): ast-grep's own
    `--inspect entity` stderr line embeds the raw path, so a path containing
    a literal newline splits that one diagnostic line into two physical
    lines; the entity-line parser must still find it and must not fall back
    to a false 'unsupported language'."""
    _astgrep_or_skip()
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "a\nb.ts"
    fixture.write_text("export function ok() {}\n", encoding="utf-8")
    result = sk.skeleton(str(fixture))
    assert not result.refused, result.text
    assert "typescript" in result.text
    assert "ts-exported-symbols" in result.text
    assert "[1]" in result.text


@pytest.mark.parametrize(
    "source,expected_lines",
    [
        ("import os\n\x0c\ndef f():\n    pass\n", 4),
        ('x = "a b"\ndef f():\n    pass\n', 3),
    ],
)
def test_header_line_count_matches_ast_not_splitlines(tmp_path, monkeypatch, source, expected_lines):
    """AC-3 (LOW #5): the header's line count matches `ast`'s own line
    breaks (`\\n`/`\\r`/`\\r\\n` only), not `str.splitlines()`'s broader set
    (form feed, U+2028, ...), which would claim more lines than any entry's
    range, or the file's real line count, ever shows."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "lines.py"
    fixture.write_text(source, encoding="utf-8")
    result = sk.skeleton(str(fixture))
    header = result.text.splitlines()[0]
    assert header.endswith(f"(python, {expected_lines} lines)"), header
    # The bug this pins: str.splitlines() would have claimed MORE lines.
    assert len(source.splitlines()) > expected_lines


def test_astgrep_subprocess_uses_utf8_encoding_not_locale_text_mode(tmp_path, monkeypatch):
    """AC-7 (LOW #6): ast-grep's stdout/stderr are decoded with an explicit
    `encoding='utf-8', errors='replace'`, not the locale-dependent
    `text=True` mode, so a non-UTF-8-locale environment cannot mojibake or
    crash on non-ASCII match text."""
    _astgrep_or_skip()
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "a.ts"
    fixture.write_text("export function ok() {}\n", encoding="utf-8")

    calls = []
    real_run = subprocess.run

    def _capture(*args, **kwargs):
        calls.append((args, kwargs))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(sk.subprocess, "run", _capture)
    result = sk.skeleton(str(fixture))
    assert not result.refused, result.text
    # `subprocess` is one shared module object, so this also captures
    # unrelated calls made through the SAME process-wide subprocess module
    # (e.g. profile_cache.field()'s own profile-resolve.py spawn) — filter
    # to the ast-grep invocation itself.
    astgrep_calls = [(a, k) for a, k in calls if "ast-grep" in " ".join(map(str, a[0]))]
    assert astgrep_calls, "ast-grep's subprocess.run was never called"
    for _args, kwargs in astgrep_calls:
        assert kwargs.get("encoding") == "utf-8", kwargs
        assert kwargs.get("errors") == "replace", kwargs
        assert not kwargs.get("text"), kwargs


def test_klc_skeleton_double_dash_separator_accepts_path(tmp_path, monkeypatch):
    """AC-1 (LOW #7): `klc skeleton -- -x.ts` accepts the path after the
    standard `--` separator, for a path that itself begins with `-`."""
    _astgrep_or_skip()
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "-x.ts"
    fixture.write_text("export function ok() {}\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(KLC), "skeleton", "--", str(fixture)],
        env={**os.environ, "PROJECT_ROOT": str(tmp_path),
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" not in proc.stderr
