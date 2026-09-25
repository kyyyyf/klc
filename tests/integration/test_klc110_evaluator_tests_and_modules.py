"""tests/integration/test_klc110_evaluator_tests_and_modules.py — KLC-110
step-3: the tests-recall arrow (AC-4) and the affected-modules-hint arrow
(AC-5), plus the AC-4 "no other predicate" guard reusing KLC-109's existing
AST scanner rather than adding a second matcher (D-302)."""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402

_RETRIEVAL_EVAL_PY = _FW_ROOT / "core" / "skills" / "retrieval_eval.py"
_GUARD_PY = Path(__file__).resolve().parent / "test_klc109_guard.py"
_spec = importlib.util.spec_from_file_location("klc109_guard", _GUARD_PY)
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)


def _trace(**kw):
    base = {"status": "ok", "confidence": "medium", "mode": "deterministic",
            "files_likely_to_edit": [], "files_to_read_first": [],
            "tests_to_read_or_run": [], "affected_modules_hint": []}
    base.update(kw)
    return base


def test_tests_to_read_or_run_recall_via_is_test_path_only():
    """AC-4: the evaluator computes the recall of tests_to_read_or_run
    against the changed files that are test files, classifying test files
    through test_conventions.is_test_path and through no other predicate
    (build-time substitution for the deleted test_map.is_test_file, D-302)."""
    committed_paths = {"tests/integration/test_klc110_scorer.py",
                        "core/skills/retrieval_eval.py"}
    trace = _trace(tests_to_read_or_run=["tests/integration/test_klc110_scorer.py"])
    rec = _reval.evaluate(trace, set(), committed_paths)
    arrow = rec["tests_to_read_or_run"]
    assert arrow["recall"] == 1.0
    assert arrow["precision"] == 1.0


def test_affected_modules_hint_subset_superset_precision_recall():
    """AC-5: the evaluator records the subset and superset relations of
    affected_modules_hint against the modules the diff touched, together
    with precision, recall, missed and extra module names."""
    trace = _trace(affected_modules_hint=["core-skills"])
    committed_modules = {"core-skills", "tests"}
    rec = _reval.evaluate(trace, committed_modules, {"a.py"})
    arrow = rec["affected_modules_hint"]
    assert arrow["is_subset"] is True
    assert arrow["is_superset"] is False
    assert arrow["precision"] == 1.0
    assert arrow["missed"] == ["tests"]


def test_no_test_files_in_diff_marks_test_recall_unavailable():
    """A-006: a ticket that changed no test file at all records the
    test-recall arrow as unavailable, never as a 0."""
    trace = _trace(tests_to_read_or_run=[])
    rec = _reval.evaluate(trace, set(), {"core/skills/retrieval_eval.py"})
    arrow = rec["tests_to_read_or_run"]
    assert arrow["status"] == "unavailable"
    assert "reason" in arrow


def test_retrieval_eval_defines_no_private_test_file_matcher():
    """AC-4: the "no other predicate" clause is guarded by KLC-109's existing
    AST scanner (reused, not duplicated) — retrieval_eval.py defines no
    private is_test-shaped predicate and no test-path pattern literal."""
    assert _guard.scan(_RETRIEVAL_EVAL_PY) == []


def test_the_matcher_guard_bites_on_an_injected_private_predicate(tmp_path):
    """AC-4 fail-closed twin: the scanner does bite when a private
    test-file matcher is injected into a copy of retrieval_eval.py, proving
    the guard is not vacuously green."""
    copy = tmp_path / "retrieval_eval_copy.py"
    shutil.copy(_RETRIEVAL_EVAL_PY, copy)
    with copy.open("a", encoding="utf-8") as fh:
        fh.write("\n\ndef _is_test_path(path):\n    return '__tests__' in path\n")
    violations = _guard.scan(copy)
    assert violations
