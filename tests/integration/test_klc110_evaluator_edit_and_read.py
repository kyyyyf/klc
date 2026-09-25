"""tests/integration/test_klc110_evaluator_edit_and_read.py — KLC-110 step-3:
the evaluator's edit and read-first arrows (AC-2, AC-3)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402


def _trace(**kw):
    base = {"status": "ok", "confidence": "medium", "mode": "deterministic",
            "files_likely_to_edit": [], "files_to_read_first": [],
            "tests_to_read_or_run": [], "affected_modules_hint": []}
    base.update(kw)
    return base


def test_precision_recall_at_5_for_files_likely_to_edit():
    """AC-2: the evaluator computes precision@5, recall@5 and the matched,
    missed and extra file lists for files_likely_to_edit against the
    ticket's committed changed files."""
    trace = _trace(files_likely_to_edit=["a.py", "b.py", "z.py"])
    committed_paths = {"a.py", "b.py", "c.py"}
    rec = _reval.evaluate(trace, set(), committed_paths)
    arrow = rec["files_likely_to_edit"]
    assert arrow["precision"] == 2 / 3
    assert arrow["recall"] == 2 / 3
    assert arrow["matched"] == ["a.py", "b.py"]
    assert arrow["missed"] == ["c.py"]
    assert arrow["extra"] == ["z.py"]


def test_precision_recall_at_10_and_files_before_first_edit_for_files_to_read_first():
    """AC-3: the evaluator computes precision@10, recall@10 and the
    files-before-first-edit count for files_to_read_first against the same
    ground truth, through the same shared function AC-1 exposes."""
    trace = _trace(files_to_read_first=["x.py", "a.py", "b.py"])
    committed_paths = {"a.py", "b.py", "c.py"}
    rec = _reval.evaluate(trace, set(), committed_paths)
    arrow = rec["files_to_read_first"]
    assert arrow["precision"] == 2 / 3
    assert arrow["recall"] == 2 / 3
    assert arrow["items_before_first_hit"] == 1  # x.py misses, a.py hits at position 2
