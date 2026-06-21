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
_CONFLICT_RE = re.compile(r"\[!CONFLICT\b[^\]]*\]", re.IGNORECASE)
# Stub AC: checklist line whose body ends right after the label (optionally a bare colon).
_STUB_AC_RE = re.compile(r"(?m)^[ \t]*-[ \t]*\[[ xX]\][ \t]*(AC-\d+)[ \t]*:?[ \t]*$")


def scan_spec(text: str) -> list[dict]:
    """Return structured violations. Each: {'class': str, 'phrase': str, 'offset': int}."""
    violations: list[dict] = []

    # Strip fenced blocks and inline code before placeholder scan to avoid false positives.
    stripped = _FENCED_CODE_RE.sub("", text)
    stripped = _INLINE_CODE_RE.sub("", stripped)

    for token in PLACEHOLDER_TOKENS:
        if token == "...":
            pat = re.compile(r"(?<![\w.])\.\.\.(?![\w.])")
        else:
            pat = re.compile(r"\b" + re.escape(token) + r"\b")
        for m in pat.finditer(stripped):
            violations.append({"class": "placeholder", "phrase": token, "offset": m.start()})

    for m in _CONFLICT_RE.finditer(text):
        violations.append({"class": "conflict", "phrase": m.group(0), "offset": m.start()})

    for m in _STUB_AC_RE.finditer(text):
        violations.append({"class": "stub_ac", "phrase": m.group(0).strip(), "offset": m.start()})

    return violations


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="spec self-review scanner")
    ap.add_argument("--file", required=True, help="spec file to scan")
    args = ap.parse_args(argv)
    text = Path(args.file).read_text(encoding="utf-8")
    hits = scan_spec(text)
    print(json.dumps({"violations": hits}, indent=2))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
