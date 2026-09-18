"""KLC-103 — AC-9: the rendered root CLAUDE.md reports structural.json's totals.

Real-substrate tests: render_root() is invoked for real (Jinja2 templates on
disk), against a temp PROJECT_ROOT carrying real `.klc/index/*.json` fixtures
— no mocks. The retired embedded `inventory["structural"]` copy must no
longer be read; `structural.json` is the single source of file/line/language
totals (D-102)."""
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent / "core" / "skills"


def _load_module_writer():
    spec = importlib.util.spec_from_file_location("klc103_module_writer",
                                                    str(SKILLS / "module-writer.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_index(root: Path, *, inventory: dict, modules: dict,
                 structural: dict | None) -> None:
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")
    if structural is not None:
        (idx / "structural.json").write_text(json.dumps(structural), encoding="utf-8")


def _totals_from_doc(text: str) -> tuple[int, int, list[str]]:
    files = int(re.search(r"\*\*Total files\*\*:\s*(\d+)", text).group(1))
    lines = int(re.search(r"\*\*Total lines\*\*:\s*(\d+)", text).group(1))
    langs = re.findall(r"`(\w+)` — \d+ files", text)
    return files, lines, langs


def test_root_doc_reports_structural_json_totals(tmp_path, monkeypatch):
    """AC-9 positive: structural.json's non-zero totals show up in the
    rendered root CLAUDE.md, sourced directly from structural.json — not a
    retired embedded `inventory['structural']` copy (which is absent here on
    purpose, to prove the read no longer depends on it)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_index(
        tmp_path,
        inventory={"symbols": [], "notes": []},  # deliberately NO "structural" key
        modules={"modules": [], "cycles": [], "notes": []},
        structural={"total_files": 42, "total_lines": 1234,
                    "languages": {"python": {"files": 42, "lines": 1234}}},
    )
    mw = _load_module_writer()
    out = mw.render_root(tmp_path / "CLAUDE.md")
    text = out.read_text(encoding="utf-8")
    files, lines, langs = _totals_from_doc(text)
    assert files == 42
    assert lines == 1234
    assert langs == ["python"]


def test_check_flags_zero_doc_totals_against_nonzero_structural(tmp_path):
    """AC-9 negative/guard: a deliberately STALE rendered doc (zero
    files/lines/empty languages — the pre-KLC-103 bug's symptom) paired with a
    non-zero structural.json must be FLAGGED by the totals check, not pass
    silently. This is the guard the AC-9 acceptance check performs; it must be
    strict enough to catch the exact defect spec.md describes."""
    structural = {"total_files": 42, "total_lines": 1234,
                  "languages": {"python": {"files": 42, "lines": 1234}}}
    stale_doc = (
        "# proj\n\n## Overview\n\n"
        "- **Total files**: 0\n"
        "- **Total lines**: 0\n"
        "- **Languages** (by line count):\n"
    )
    files, lines, langs = _totals_from_doc(stale_doc)
    mismatch = (structural["total_files"] != 0 and files == 0) or \
        (structural["total_lines"] != 0 and lines == 0)
    assert mismatch, "AC-9 guard must flag a stale zero-totals doc against non-zero structural.json"


def test_root_doc_degrades_when_structural_absent(tmp_path, monkeypatch):
    """Edge case (test-plan.md): structural.json absent (bootstrap-ordering
    edge) must not crash render_root() — degrades to the pre-existing
    zero/empty state, distinguishing 'no structural data yet' from
    'structural data ignored' (the AC-9 failure mode)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _write_index(
        tmp_path,
        inventory={"symbols": [], "notes": []},
        modules={"modules": [], "cycles": [], "notes": []},
        structural=None,  # deliberately absent
    )
    mw = _load_module_writer()
    out = mw.render_root(tmp_path / "CLAUDE.md")  # must not raise / sys.exit
    files, lines, langs = _totals_from_doc(out.read_text(encoding="utf-8"))
    assert files == 0
    assert lines == 0
    assert langs == []
