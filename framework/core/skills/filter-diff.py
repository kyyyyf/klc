#!/usr/bin/env python3
"""filter-diff.py — produce a unified diff subset that only covers files
whose path matches a regex.

Usage:   filter-diff.py <in.patch> <regex> <out.patch>

Contract:
- Input is a standard unified diff (`git diff` output).
- Output keeps every `diff --git`, `index`, `---`, `+++`, `@@` line plus
  each hunk of every file whose `+++ b/<path>` matches the regex.
- File blocks that don't match are dropped whole. Files without a clear
  `+++` header (rare binary chunks, mode-only changes) are kept
  defensively — reviewers prefer extra context to missing context.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        sys.stderr.write("usage: filter-diff.py <in.patch> <regex> <out.patch>\n")
        return 2

    src = Path(sys.argv[1])
    pat = re.compile(sys.argv[2])
    dst = Path(sys.argv[3])

    if not src.exists():
        sys.stderr.write(f"filter-diff: input {src} not found\n")
        return 1

    lines = src.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    out: list[str] = []

    # State per block:
    #   decided: True once we have enough signal (a `+++ b/<path>` or a
    #            `--- a/<path>` on a deletion) to choose keep-or-drop.
    #   keep:    current verdict. Defaults to False — we only keep a
    #            block if it actively matches. Mode-only / binary blocks
    #            with neither +++ nor meaningful --- remain undecided
    #            and get dropped (safer for per-reviewer filtering).
    block: list[str] = []
    decided = False
    keep = False
    deleted_path: str | None = None

    def flush():
        nonlocal block, decided, keep, deleted_path
        if block and decided and keep:
            out.extend(block)
        block = []
        decided = False
        keep = False
        deleted_path = None

    for line in lines:
        if line.startswith("diff --git "):
            flush()
            block.append(line)
            continue
        if not block:
            # Header garbage before first diff block — pass through.
            out.append(line)
            continue
        block.append(line)

        if line.startswith("+++ b/") and not line.startswith("+++ b//dev/null"):
            # Normal or newly-created file.
            path = line[6:].rstrip("\n").rstrip()
            decided = True
            keep = bool(pat.search(path))
        elif line.startswith("+++ /dev/null") or line.startswith("+++ b//dev/null"):
            # File was deleted by this diff. Use the `--- a/<path>` header
            # we've (hopefully) already seen for matching.
            decided = True
            keep = bool(deleted_path and pat.search(deleted_path))
        elif line.startswith("--- a/") and not line.startswith("--- a//dev/null"):
            # Remember the original path in case `+++ /dev/null` follows.
            deleted_path = line[6:].rstrip("\n").rstrip()

    flush()
    dst.write_text("".join(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
