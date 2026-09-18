#!/usr/bin/env python3
"""KLC-103 — AC-10: language detection derives the project language set from a
key a producer actually writes (structural.json's languages.<lang>.files), not
the phantom inventory["extensions"] that no producer ever wrote."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))


def test_detect_over_klc_repo_returns_nonempty_set_containing_python(tmp_path):
    """Real substrate, no fixture: this klc checkout's own files ARE what
    detect() must see language stats for — but `.klc/index/` is gitignored
    (.gitignore:6) and does not exist on a fresh clone/worktree checkout, so
    this test must never read whatever `structural.json` happens to already be
    on disk at the ambient `PROJECT_ROOT` (review HIGH finding: that version
    only passed in one long-lived dev directory seasoned by repeated
    `klc init`/`klc update` runs, and failed on a fresh `git worktree`
    checkout of the same commit).

    Mirrors tests/integration/test_klc105_real_repo_closure.py: build
    structural.json FRESH in-process via file_scanner.scan(FRAMEWORK_ROOT) into
    a throwaway tmp_path/.klc/index/, then point detect() at that tmp dir
    (never the real `.klc/index/`) via the same klc_index_dir monkeypatch
    tests/test_detect_languages_malformed.py already uses."""
    import file_scanner
    import detect_languages

    structural = file_scanner.scan(FRAMEWORK_ROOT)
    klc_index = tmp_path / ".klc" / "index"
    klc_index.mkdir(parents=True)
    (klc_index / "structural.json").write_text(
        json.dumps(structural), encoding="utf-8")

    original_klc_index_dir = detect_languages.klc_index_dir
    detect_languages.klc_index_dir = lambda: klc_index
    try:
        languages = detect_languages.detect()
    finally:
        detect_languages.klc_index_dir = original_klc_index_dir

    assert languages, "detect() must return a non-empty set over the real klc repo"
    assert "python" in languages
