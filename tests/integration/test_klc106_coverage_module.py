"""KLC-106 step-1 — the shared coverage module (AC-1, AC-2, AC-3).

One module, ``core/skills/index_coverage.py``, turns an observed count and a
universe count into the verdict record every builder in this ticket stamps.
Its arithmetic must carry no language name, no tool name and no file
extension — a fifth-language builder written next year complies by calling
the same two functions, not by copying a per-tool patch.
"""
from __future__ import annotations

import re
import sys
import tokenize
import io
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import index_coverage  # noqa: E402
import settings  # noqa: E402

_VERDICT_KEYS = {"builder", "artifact", "metric", "observed", "universe",
                  "ratio", "threshold", "degraded", "reason"}

# Literals that must never appear in the module's ARITHMETIC (AC-1: no
# language name, tool name or file extension in its logic). Docstrings and
# comments legitimately name them as examples, so this greps only lines that
# are not comments/docstrings — see test body.
_FORBIDDEN_LITERALS = ("python", "typescript", "rust", "madge", "pipdeptree",
                        "cargo", "cmake", ".ts", ".py", ".rs")


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    """A project config dir and a framework config dir, both injected —
    mirrors tests/test_settings.py's fixture of the same name."""
    proj = tmp_path / "proj_config"
    fw = tmp_path / "fw_config"
    proj.mkdir()
    fw.mkdir()
    monkeypatch.setattr(settings, "_proj_config", lambda: proj)
    monkeypatch.setattr(settings, "_fw_config", lambda: fw)
    return proj, fw


def _w(d: Path, name: str, text: str) -> None:
    (d / name).write_text(text, encoding="utf-8")


# --------------------------------------------------------------------- AC-1

# Review round 2, drift F-1: the AC-1 literal scanner below (inside
# test_verdict_record_shape_is_tool_and_language_agnostic) uses a naive
# `line.strip().startswith('"""')` toggle to skip docstrings. That toggle
# fires on ANY line starting with a triple-quote regardless of whether it
# ALSO closes on the same line (a self-contained one-line docstring wrongly
# flips docstring-mode ON), and it never detects a multi-line docstring's
# CLOSE when the closing `"""` shares a line with trailing prose (the shape
# nearly every real docstring in index_coverage.py uses, e.g. threshold_for's
# own multi-line docstring) — so `in_docstring` gets stuck True and silently
# swallows most of the file's real executable code from the scan. D-215
# replaces it with `_code_only`, a `tokenize`-based classifier (not yet
# defined — the two tests below are RED until it lands) that knows the real
# span of every STRING and COMMENT token regardless of how it opens/closes
# on the source's physical lines.
def _code_only(src: str) -> str:
    """Return *src* with every COMMENT token and every triple-quoted STRING
    token (docstrings, single- or multi-line, however they open/close)
    blanked out, leaving only characters that are genuinely executable
    logic. Built on `tokenize` rather than a line-prefix toggle so it never
    mis-tracks state across a docstring's real start/end span (D-215)."""
    lines = [list(line) for line in src.splitlines()]
    tokens = tokenize.generate_tokens(io.StringIO(src).readline)
    for tok_type, string, start, end, _ in tokens:
        is_triple_quoted_string = (
            tok_type == tokenize.STRING
            and string.lstrip("rRbBuUfF").startswith(('"""', "'''")))
        if tok_type != tokenize.COMMENT and not is_triple_quoted_string:
            continue
        (sr, sc), (er, ec) = start, end
        if sr == er:
            row = lines[sr - 1]
            for i in range(sc, min(ec, len(row))):
                row[i] = " "
            continue
        row = lines[sr - 1]
        for i in range(sc, len(row)):
            row[i] = " "
        for r in range(sr, er - 1):
            lines[r] = [" "] * len(lines[r])
        row = lines[er - 1]
        for i in range(0, min(ec, len(row))):
            row[i] = " "
    return "\n".join("".join(line) for line in lines)


def test_code_only_does_not_swallow_code_after_a_docstring_that_closes_inline():
    """Meta-test for the AC-1 scanner's own classifier: a multi-line
    docstring whose CLOSING `\"\"\"` shares a physical line with trailing
    prose (index_coverage.py's own shape, e.g. threshold_for's docstring)
    must not swallow the real code that follows it. Before D-215's fix, the
    old `line.strip().startswith('\"\"\"')` toggle never detects that closing
    line (it does not START with the marker), so `in_docstring` stays True
    forever and a forbidden literal sitting in REAL logic right after such a
    docstring goes undetected — the exact failure mode drift review F-1
    found live in index_coverage.py's own multi-line docstrings."""
    src = (
        'def f():\n'
        '    """Opens here on this line\n'
        '    and closes on THIS line, with trailing code before it."""\n'
        '    return "python"  # forbidden literal, must be visible as CODE\n'
    )
    code = _code_only(src).lower()
    assert "python" in code
    assert "opens here" not in code
    assert "closes on this line" not in code


def test_code_only_does_not_toggle_on_a_single_line_docstring():
    """A docstring that opens AND closes on the SAME line must not flip
    docstring-mode on at all (a net no-op) — before D-215, the naive toggle
    treated `stripped.startswith('\"\"\"')` as an open regardless of whether
    the same line already closed it, so the line immediately after a
    single-line docstring was wrongly classified as still inside one."""
    src = (
        'def f():\n'
        '    """One line only."""\n'
        '    return "rust"  # forbidden literal on the very next line\n'
    )
    code = _code_only(src).lower()
    assert "rust" in code
    assert "one line only" not in code


def test_verdict_record_shape_is_tool_and_language_agnostic():
    v = index_coverage.verdict(
        "dep_graph:scanner", "depgraph.json", 10, 20, metric="node-coverage")
    assert set(v.keys()) == _VERDICT_KEYS
    assert v["builder"] == "dep_graph:scanner"
    assert v["artifact"] == "depgraph.json"
    assert v["observed"] == 10
    assert v["universe"] == 20
    assert v["ratio"] == 0.5
    assert isinstance(v["degraded"], bool)
    assert isinstance(v["reason"], str) and v["reason"]

    src = (Path(__file__).resolve().parent.parent.parent
           / "core" / "skills" / "index_coverage.py").read_text(encoding="utf-8")
    # Strip comments and docstrings/strings that merely document the module —
    # what must be absent is the literal appearing in executable logic, e.g.
    # `if lang == "typescript"`. A conservative proxy: no forbidden literal
    # appears anywhere outside of a `#`-comment or a triple-quoted docstring.
    # D-215 (drift review round 2, F-1): this used to be a hand-rolled
    # `line.strip().startswith('"""')` toggle, which mis-tracked state across
    # this file's own multi-line docstrings (most close inline, with trailing
    # prose before the closing marker, so the toggle's OPEN fired but its
    # CLOSE never did) and silently excluded most of the file's real logic
    # from the scan. `_code_only` uses `tokenize` instead, which knows each
    # STRING/COMMENT token's real span regardless of its physical shape.
    code_text = _code_only(src).lower()
    for literal in _FORBIDDEN_LITERALS:
        assert literal not in code_text, (
            f"forbidden literal {literal!r} found in index_coverage.py logic")


# --------------------------------------------------------------------- AC-2

def test_threshold_resolved_from_settings_ladder_project_before_framework_before_default(scopes):
    proj, fw = scopes
    assert index_coverage.threshold_for("dep_graph") == index_coverage.DEFAULT_THRESHOLD
    _w(fw, "settings.yml", "index:\n  coverage:\n    min_ratio: 0.4\n")
    assert index_coverage.threshold_for("dep_graph") == 0.4
    _w(proj, "settings.yml", "index:\n  coverage:\n    min_ratio: 0.6\n")
    assert index_coverage.threshold_for("dep_graph") == 0.6


def test_per_builder_threshold_override_wins_over_default(scopes):
    proj, fw = scopes
    _w(proj, "settings.yml",
       "index:\n  coverage:\n    min_ratio: 0.4\n    per_builder:\n      dep_graph: 0.9\n")
    assert index_coverage.threshold_for("dep_graph") == 0.9
    assert index_coverage.threshold_for("symbol_usage") == 0.4


# --------------------------------------------------------------------- AC-3

def test_denominator_resolves_language_scoped_vs_agnostic_from_structural_json():
    structural = {
        "total_files": 100,
        "languages": {"python": {"files": 40}, "typescript": {"files": 5}},
    }
    assert index_coverage.universe_for(None, structural) == 100
    assert index_coverage.universe_for("python", structural) == 40
    assert index_coverage.universe_for("go", structural) is None


def test_denominator_falls_back_to_structural_when_klc105_universe_artifact_absent():
    structural = {"total_files": 12, "languages": {"python": {"files": 12}}}
    assert index_coverage.universe_for(None, structural, universe_artifact=None) == 12
    assert index_coverage.universe_for(None, None, universe_artifact=None) == 0
