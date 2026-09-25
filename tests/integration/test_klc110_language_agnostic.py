"""tests/integration/test_klc110_language_agnostic.py — KLC-110 step-7:
AC-19. Every scoring, classification and aggregation path this ticket adds
contains no file extension, no language name, no external tool name.
Follows the KLC-121 grep-style guard's shape."""
from __future__ import annotations

import ast
import re
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_RETRIEVAL_EVAL = _FW_ROOT / "core" / "skills" / "retrieval_eval.py"
_PLANNING_EVAL = _FW_ROOT / "core" / "skills" / "planning-eval.py"
_METRICS = _FW_ROOT / "core" / "skills" / "metrics.py"

# C-001/AC-19's three forbidden categories: file extensions (as string
# literals), language names, and named external tools.
_EXT_LITERAL_RE = re.compile(r'["\']\.[A-Za-z][A-Za-z0-9]{0,4}["\']')
_LANGUAGE_NAMES = ("python", "typescript", "javascript", "rust", "golang",
                   " java ", "kotlin", "ruby", " php ", "swift", "csharp")
_TOOL_NAMES = ("ast-grep", "ast_grep", "madge", "tsc", "cargo", "cmake")


def _strip_comments_and_docstrings(source: str) -> str:
    """Drop triple-quoted docstrings (legitimate PROSE that may name a
    language/tool while explaining a design decision) and `#`-comments, so
    the grep below checks CODE only."""
    no_triple = re.sub(r'"""(?:.|\n)*?"""', "", source)
    no_triple = re.sub(r"'''(?:.|\n)*?'''", "", no_triple)
    return re.sub(r"#.*", "", no_triple)


def _function_source(path: Path, names: set[str]) -> str:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            seg = ast.get_source_segment(src, node) or ""
            out.append(seg)
    return "\n".join(out)


def test_scoring_classification_aggregation_code_has_no_file_extension_or_language_name():
    """AC-19: every scoring, classification and aggregation path added by
    this ticket contains no file extension, no language name, no external
    tool name — `retrieval_eval.py` (wholly new to this ticket) plus the
    backfill and rollup functions added to `planning-eval.py`/`metrics.py`."""
    pieces = [_RETRIEVAL_EVAL.read_text(encoding="utf-8")]
    pieces.append(_function_source(_PLANNING_EVAL, {"backfill_rows", "render_backfill"}))
    pieces.append(_function_source(_METRICS, {"_retrieval_rollup", "_per_confidence"}))

    code = _strip_comments_and_docstrings("\n".join(pieces))

    ext_hits = _EXT_LITERAL_RE.findall(code)
    assert not ext_hits, f"file-extension literal(s) found in code: {ext_hits}"

    lowered = code.lower()
    lang_hits = [name for name in _LANGUAGE_NAMES if name.strip().lower() in lowered]
    assert not lang_hits, f"language name(s) found in code: {lang_hits}"

    tool_hits = [name for name in _TOOL_NAMES if name.lower() in lowered]
    assert not tool_hits, f"external-tool name(s) found in code: {tool_hits}"
