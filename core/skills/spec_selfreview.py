"""Spec self-review scanner — canonical token set + structural violation detector.

scan_spec(text) -> list[dict]  returns violations for three classes:
  placeholder  — a PLACEHOLDER_TOKEN outside inline code / fenced blocks
  conflict     — an unresolved [!CONFLICT ...] marker
  stub_ac      — an AC-N checklist line with no body beyond the label

PLACEHOLDER_TOKENS is the single canonical source; tests/prompt_harness.py
imports it from here so the two cannot drift (KLC-033).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

PLACEHOLDER_TOKENS = ("TODO", "TBD", "write tests", "<...>", "...")

_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
# Scans stripped text (fences + inline code removed).
_CONFLICT_RE = re.compile(r"\[!CONFLICT\b[^\]]*\]", re.IGNORECASE)
# Stub AC: checklist line whose body ends right after the label (optionally a bare colon).
_STUB_AC_RE = re.compile(r"(?m)^[ \t]*-[ \t]*\[[ xX]\][ \t]*(AC-\d+)[ \t]*:?[ \t]*$")

# Precompile one pattern per token so scan_spec() pays no compile cost per call.
_TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (token,
     re.compile(r"(?<![\w.])\.\.\.(?![\w.])") if token == "..."
     else re.compile(r"\b" + re.escape(token) + r"\b"))
    for token in PLACEHOLDER_TOKENS
]


def scan_spec(text: str) -> list[dict]:
    """Return structured violations. Each: {'class': str, 'phrase': str, 'offset': int}."""
    violations: list[dict] = []

    # Strip fenced blocks and inline code before scanning to avoid false positives.
    stripped = _FENCED_CODE_RE.sub("", text)
    stripped = _INLINE_CODE_RE.sub("", stripped)

    for token, pat in _TOKEN_PATTERNS:
        for m in pat.finditer(stripped):
            violations.append({"class": "placeholder", "phrase": token, "offset": m.start()})

    for m in _CONFLICT_RE.finditer(stripped):
        violations.append({"class": "conflict", "phrase": m.group(0), "offset": m.start()})

    for m in _STUB_AC_RE.finditer(text):
        violations.append({"class": "stub_ac", "phrase": m.group(0).strip(), "offset": m.start()})

    return violations


_BUG_SECTIONS = ("Reproduction", "Observed vs expected", "Root cause",
                 "Why existing tests missed it")
_AC_LINE_RE = re.compile(r"(?im)^[ \t]*-[ \t]*\[[ x]\][ \t]*AC-\d+\b.*$")


def _section_body(stripped: str, title: str) -> str | None:
    m = re.search(r"(?im)^##[ \t]+" + re.escape(title) + r"[ \t]*$", stripped)
    if not m:
        return None
    rest = stripped[m.end():]
    nxt = re.search(r"(?m)^##[ \t]+\S", rest)
    return rest[: nxt.start()] if nxt else rest


_REGRESSION_TEST_RE = re.compile(
    r"\bregression\b.*\btests?\b|\btests?\b.*\bregression\b")
_TEST_REF_RE = re.compile(r"\btests/\S+|\b\w+_test\.py\b|::test_\w+")


def _names_regression_test(ac: str) -> bool:
    """AC line (lower-cased) mentions a regression test, or names a concrete test
    path or node (`tests/x.py`, `x_test.py`, `::test_y`); a bare `test_name` does not count. Word boundaries, so
    'latest' never stands in for 'test'."""
    return bool(_REGRESSION_TEST_RE.search(ac) or _TEST_REF_RE.search(ac))


def spec_kind(text: str) -> str:
    """`kind:` of the spec.md frontmatter ('' when absent). Reads only the block between a
    leading '---' and the next '---'; quotes and a trailing `# comment` are tolerated."""
    m = re.match(r"\s*---[ \t]*\n(.*?)(?:\n---|\Z)", text, re.S)
    if not m:
        return ""
    k = re.search(r"(?im)^kind:[ \t]*[\"']?(\w+)[\"']?[ \t]*(?:#.*)?$", m.group(1))
    return k.group(1).lower() if k else ""


def bug_shape_violations(text: str) -> list[dict]:
    """Shape check for specs of kind bug (KLC-176). Callers apply it only when kind is bug.

    A separate detector, so scan_spec keeps its signature. Returns
    {'class': 'bug_shape', 'phrase': <missing section or 'regression test AC'>, 'offset': 0}
    for each bug section that is absent or empty, and one more when no AC line names
    a regression test. Fenced blocks are ignored.
    """
    stripped = _FENCED_CODE_RE.sub("", text)
    out: list[dict] = []
    for title in _BUG_SECTIONS:
        body = _section_body(stripped, title)
        # a body made only of headings (`### sub`) has no content
        if body is None or not re.sub(r"(?m)^[ \t]*#+.*$", "", body).strip():
            out.append({"class": "bug_shape", "phrase": f"## {title}", "offset": 0})
    acs = [m.group(0).lower() for m in _AC_LINE_RE.finditer(stripped)]
    if not any(_names_regression_test(a) for a in acs):
        out.append({"class": "bug_shape", "phrase": "an AC naming a regression test", "offset": 0})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="spec self-review scanner")
    ap.add_argument("--file", required=True, help="spec file to scan")
    args = ap.parse_args(argv)
    text = Path(args.file).read_text(encoding="utf-8")
    hits = scan_spec(text)
    out: dict = {"violations": hits}
    if spec_kind(text) == "bug":
        out["warnings"] = bug_shape_violations(text)
    print(json.dumps(out, indent=2))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
