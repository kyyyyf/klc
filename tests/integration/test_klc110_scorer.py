"""tests/integration/test_klc110_scorer.py — KLC-110 step-1: one scorer,
loaded through one canonical loader, and no second implementation
anywhere (AC-1, C-001)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "core" / "skills"
if str(_SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILLS_DIR))

import retrieval_eval as _reval  # noqa: E402


def test_precision_recall_is_one_parameterized_function_over_k():
    """AC-1: the ranking scorer inside planning-eval.py is exposed as one
    parameterised function(candidates, truth, k) that both the evaluator and
    the corpus report reach through the SAME canonical loader, so the two
    call sites resolve to the identical function object; and the one
    ranking-position metric with no shared home reports the position of the
    first hit."""
    mod_a = _reval.load_planning_eval()
    mod_b = _reval.load_planning_eval()
    assert mod_a is mod_b, "load_planning_eval() must be idempotent (D-213)"
    assert _reval.rank_metrics is mod_a.rank_metrics

    result = mod_a.rank_metrics(["a.py", "b.py", "c.py"], {"b.py"}, 5)
    assert result["items_before_first_hit"] == 1

    result_none = mod_a.rank_metrics(["a.py"], {"z.py"}, 5)
    assert result_none["items_before_first_hit"] == 1  # len(cands) — no hit at all


def test_no_second_scorer_implementation_exists():
    """C-001: no second precision/recall arithmetic exists anywhere in
    core/skills outside planning-eval.py's own rank_metrics/precision_recall."""
    pattern = re.compile(r"\b(precision|recall)\s*=.*/\s*len\(")
    violations: dict[str, list[str]] = {}
    for f in sorted(_SKILLS_DIR.glob("*.py")):
        if f.name == "planning-eval.py":
            continue
        text = f.read_text(encoding="utf-8")
        hits = [ln.strip() for ln in text.splitlines() if pattern.search(ln)]
        if hits:
            violations[f.name] = hits
    assert violations == {}, violations
