"""tests/integration/test_klc110_readonly_probe.py — KLC-110 step-5: a
read-only advisory probe leaves meta.json byte-identical and the evidence
log unchanged in length, while returning the same advisory lines the
persisting path returns (AC-10)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase_completion as _pc  # noqa: E402


def _fake_git(calls):
    def _run(args, repo=None):
        calls.append(list(args))
        if args[0] == "merge-base":
            return "deadbeef"
        if args[0] == "diff":
            return "a.py\n"
        return ""
    return _run


def test_readonly_probe_leaves_meta_json_byte_identical_and_jsonl_length_unchanged(
    tmp_path, monkeypatch
):
    """AC-10: a read-only advisory probe leaves meta.json byte-identical and
    the evidence log unchanged in length, while returning the same advisory
    lines the persisting path returns."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc" / "tickets" / "KLC-P"
    d.mkdir(parents=True)
    meta_path = d / "meta.json"
    meta_path.write_text(
        json.dumps({"phase": "integrate:work", "track": "M", "metrics": {}}, indent=2),
        encoding="utf-8")
    trace = {"status": "ok", "confidence": "high", "files_likely_to_edit": ["a.py"],
             "files_to_read_first": [], "tests_to_read_or_run": [],
             "affected_modules_hint": []}
    (d / "retrieval_trace.json").write_text(json.dumps(trace), encoding="utf-8")

    calls: list = []
    monkeypatch.setattr(_pc, "_git", _fake_git(calls))
    monkeypatch.setattr(_pc, "_load_modules", lambda: {"modules": []})

    log_path = tmp_path / ".klc" / "knowledge" / "retrieval-eval.jsonl"
    before_log_lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    before_meta_bytes = meta_path.read_bytes()

    probe_recs = _pc._retrieval_advisories("KLC-P", False)

    after_meta_bytes = meta_path.read_bytes()
    after_log_lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    assert after_meta_bytes == before_meta_bytes
    assert after_log_lines == before_log_lines

    persist_recs = _pc._retrieval_advisories("KLC-P", True)
    assert persist_recs == probe_recs  # same advisory lines either way

    after_persist_log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(after_persist_log_lines) == len(before_log_lines) + 1

    # The persisting call above staged a meta patch (module-global state);
    # tests/conftest.py's autouse `_clear_lifecycle_meta_patches` fixture
    # drains it after this test, so it cannot leak into another test in this
    # process (KLC-110 review round 1, step-9a).
