#!/usr/bin/env python3
"""KLC-121 — AC-9: the fingerprint and fallback logic branches on nothing but
the path and the recorded digest. Both tests target
`core/skills/index_fingerprint.py`, the one module C-001/D-010 designate as
language-agnostic by construction so this static assertion has exactly one
file to police."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
INDEX_FINGERPRINT = FRAMEWORK_ROOT / "core" / "skills" / "index_fingerprint.py"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args],
                    capture_output=True, text=True, timeout=15)


def test_fixture_tree_of_an_unsupported_language_gets_a_complete_fingerprint_map(tmp_path):
    """AC-9: A fixture tree of a language the framework has no extractor for
    (a made-up `.zzz` extension, absent from `file_scanner.EXT_LANG`)
    still gets a full `sha256`+`size` fingerprint entry for every such
    file — fingerprinting never gates on a recognised language."""
    repo = tmp_path / "proj"
    (repo / "widgets").mkdir(parents=True)
    (repo / "widgets" / "a.zzz").write_text("not a known language\n", encoding="utf-8")
    (repo / "widgets" / "b.zzz").write_text("also not a known language\n", encoding="utf-8")
    (repo / "widgets" / "c.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    import os
    env = dict(os.environ, PROJECT_ROOT=str(repo))
    script = FRAMEWORK_ROOT / "core" / "skills" / "file_scanner.py"
    r = subprocess.run([sys.executable, str(script), str(repo)],
                        env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr

    import json
    result = json.loads(r.stdout)
    assert "widgets/a.zzz" not in result["languages"].get("zzz", {})  # sanity: unrecognised
    for rel in ("widgets/a.zzz", "widgets/b.zzz", "widgets/c.py"):
        assert rel in result["files"], f"{rel} missing a fingerprint entry"
        assert set(result["files"][rel]) == {"sha256", "size"}
        assert result["files"][rel]["size"] > 0


# C-001's three forbidden categories: file extensions (as string literals),
# language names, and named external tools. AC-9's dispatch names ast-grep,
# madge, tsc, cargo and cmake explicitly.
_EXT_LITERAL_RE = re.compile(r'["\']\.[A-Za-z][A-Za-z0-9]{0,4}["\']')
_LANGUAGE_NAMES = ("python", "typescript", "javascript", "rust", "golang",
                    " java ", "kotlin", "ruby", " php ", "swift", "csharp")
_TOOL_NAMES = ("ast-grep", "ast_grep", "madge", "tsc", "cargo", "cmake")


def _strip_comments_and_docstrings(source: str) -> str:
    """Best-effort: drop triple-quoted string literals (module/function
    docstrings, which legitimately name languages/tools in PROSE) and
    `#`-comments, so the grep below checks CODE only."""
    no_triple = re.sub(r'"""(?:.|\n)*?"""', "", source)
    no_triple = re.sub(r"'''(?:.|\n)*?'''", "", no_triple)
    return re.sub(r"#.*", "", no_triple)


def test_fingerprint_and_fallback_source_names_no_extension_language_or_tool():
    """AC-9: Static, language-agnostic grep test in the KLC-105 style: greps
    `index_fingerprint.py`'s CODE (comments/docstrings excluded, since those
    are prose that may legitimately reference a language by name) for a file
    extension literal, a language name, or a named external tool. None may
    appear (C-001)."""
    source = INDEX_FINGERPRINT.read_text(encoding="utf-8")
    code = _strip_comments_and_docstrings(source)

    ext_hits = _EXT_LITERAL_RE.findall(code)
    assert not ext_hits, f"file-extension literal(s) found in code: {ext_hits}"

    lowered = code.lower()
    lang_hits = [name for name in _LANGUAGE_NAMES if name.strip().lower() in lowered]
    assert not lang_hits, f"language name(s) found in code: {lang_hits}"

    tool_hits = [name for name in _TOOL_NAMES if name.lower() in lowered]
    assert not tool_hits, f"external-tool name(s) found in code: {tool_hits}"


if __name__ == "__main__":
    import unittest
    unittest.main()
