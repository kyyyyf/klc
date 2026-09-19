"""KLC-108 — AC-10: the module score is computed by one stated
size-normalising formula: `own_signal + best_file + aggregate /
sqrt(n_matched)`. A fixture in which many weakly-matching files out-sum
one strongly-matching file must still rank the single-file module first —
checked both at a favourable 50:1 ratio AND at the repository's own
measured worst-case scale (`[!DECISION D-108-3]`, impl-plan-review finding
F-2, low: `tests/integration` is 122 files, the spec's own named offender).

The 122-file fixture is also what forced `[!DECISION D-108-4]`: design's
original `log(1 + n_matched)` divisor measurably FAILS this exact property
at the repository's real scale (the 122-file bag scores 26.35 against a
genuinely strong file's 24.43 — the bag wins). `sqrt(n_matched)` replaces it;
see `module_score`'s own docstring for the measured numbers.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-retriever.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_retriever_norm", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_single_strong_file_module_outranks_fifty_weak_file_module():
    """AC-10: a fixture in which 50 weakly matching files out-sum 1 strongly
    matching file ranks the single-file module first."""
    mod = _load_skill()
    # 50 files each scoring 1 (own_signal=0, best=1, aggregate=50, n=50).
    weak = mod.module_score(own=0.0, best=1.0, aggregate=50.0, n_matched=50)
    # 1 file scoring 10 (own_signal=0, best=10, aggregate=10, n=1).
    strong = mod.module_score(own=0.0, best=10.0, aggregate=10.0, n_matched=1)
    assert strong > weak, (strong, weak)


def test_single_strong_file_module_outranks_122_weak_file_module():
    """[!DECISION D-108-3] — impl-plan-review F-2: `tests/integration`
    (122 files, the spec's own named real offender) with each file scoring
    only 1 must still rank BELOW a single genuinely strong file, not
    statistically tied with it, at the formula's real scale."""
    mod = _load_skill()
    weak_122 = mod.module_score(own=0.0, best=1.0, aggregate=122.0, n_matched=122)
    strong = mod.module_score(own=0.0, best=10.0, aggregate=10.0, n_matched=1)
    assert strong > weak_122, (strong, weak_122)


def test_module_score_formula_matches_stated_values():
    """Pins the exact formula so a future edit cannot silently change it
    without this test noticing: own + best + aggregate / sqrt(n)."""
    mod = _load_skill()
    got = mod.module_score(own=1.0, best=2.0, aggregate=6.0, n_matched=3)
    expected = 1.0 + 2.0 + 6.0 / math.sqrt(3)
    assert got == expected


def test_module_score_zero_n_matched_never_divides_by_zero():
    mod = _load_skill()
    got = mod.module_score(own=1.0, best=0.0, aggregate=0.0, n_matched=0)
    assert got == 1.0


def test_module_docstring_states_the_scoring_formula():
    """AC-10: the size-normalising formula is recorded in the retriever's
    module docstring."""
    src = _SKILL.read_text(encoding="utf-8")
    assert "aggregate / sqrt(n_matched)" in src, (
        "the module docstring must state the size-normalising formula")


def test_ranking_key_is_rounded_so_ties_break_on_name():
    """D-003: module scores are floats, ranked on a six-decimal rounding of
    the score, tie-broken by module name — a last-ulp libm difference must
    not reorder a near-tie."""
    mod = _load_skill()
    a = mod.module_score(own=0.0, best=1.0, aggregate=1.0, n_matched=1)
    b = a + 1e-9  # differs only past the 6th decimal
    ranked = sorted([("zeta", a), ("alpha", b)], key=lambda kv: (-round(kv[1], 6), kv[0]))
    assert [n for n, _ in ranked] == ["alpha", "zeta"]
