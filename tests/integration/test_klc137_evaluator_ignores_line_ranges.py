"""KLC-137 step-4 — the evaluator family scores a trace with `line_ranges`
exactly as it scores the same trace with the key removed (AC-8).
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _klc137_fixtures import retriever_views  # noqa: E402

pytestmark = pytest.mark.usefixtures("hermetic_project_root")


def _import_skill(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, str(SKILLS / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _real_trace_with_ranges(tmp_path):
    pr = _import_skill("klc137_pr_eval", "planning-retriever.py")
    modules, fr, module_edges, test_map, inv, token_idf = retriever_views(tmp_path, "base")
    trace = pr.build_trace("widget", "deterministic", modules, fr, module_edges, test_map,
                           inventory=inv, token_idf=token_idf)
    assert trace["line_ranges"], "fixture must produce a non-empty line_ranges"
    return trace


def test_retrieval_eval_planning_eval_and_planning_validate_score_identically_with_and_without_line_ranges(tmp_path):
    """AC-8: `retrieval_eval.evaluate`, `planning-eval._retrieval_for_ticket`
    and `planning_validate.validate` produce field-by-field identical
    records for a real trace with and without `line_ranges` — none of the
    three reads that key."""
    trace = _real_trace_with_ranges(tmp_path)
    trace_no_ranges = copy.deepcopy(trace)
    trace_no_ranges.pop("line_ranges")

    re_mod = _import_skill("klc137_retrieval_eval", "retrieval_eval.py")
    committed_paths = {"pkg/widgets.py"}
    committed_modules = {"pkg"}
    rec_with = re_mod.evaluate(trace, committed_modules, committed_paths)
    rec_without = re_mod.evaluate(trace_no_ranges, committed_modules, committed_paths)
    assert rec_with == rec_without

    pe_mod = _import_skill("klc137_planning_eval", "planning-eval.py")
    relevant = {"pkg/widgets.py"}
    row_with = pe_mod._retrieval_for_ticket(trace, relevant)
    row_without = pe_mod._retrieval_for_ticket(trace_no_ranges, relevant)
    assert row_with == row_without
    assert row_with is not None

    pv_mod = _import_skill("klc137_planning_validate", "planning_validate.py")
    modules_doc = {"modules": [{"name": "pkg", "path": "pkg/", "files": []}]}
    file_roles_doc = {"files": {"pkg/widgets.py": {}, "pkg/other.py": {}}}
    result_with = pv_mod.validate(modules_doc, file_roles=file_roles_doc, retrieval=trace)
    result_without = pv_mod.validate(modules_doc, file_roles=file_roles_doc, retrieval=trace_no_ranges)
    assert result_with == result_without


def test_bad_arrow_field_returns_none_for_a_trace_carrying_line_ranges(tmp_path):
    """AC-8 (impl-plan-review F-6): `_bad_arrow_field` returns `None` for a
    real, well-formed trace that carries `line_ranges` — first asserts the
    trace really has a non-empty `line_ranges`, so this cannot pass
    vacuously on a trace the key never touched."""
    trace = _real_trace_with_ranges(tmp_path)
    re_mod = _import_skill("klc137_retrieval_eval_2", "retrieval_eval.py")
    assert re_mod._bad_arrow_field(trace) is None
