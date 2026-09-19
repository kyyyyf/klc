"""KLC-108 — AC-9: `score_file` and the module signal weight a token by that
artifact's inverse document frequency; no literal stop-word list
participates in SCORING (down-weighting comes only from the IDF lookup)."""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-retriever.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_retriever_idf", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_token_present_in_more_files_scores_strictly_less():
    """AC-9: a token present in more files contributes strictly less than a
    token present in fewer files."""
    mod = _load_skill()
    # 'rare' in 2 of 50 files (high IDF); 'common' in 40 of 50 (low IDF).
    idf = {"tokens": {"rare": 3.0, "common": 0.5}, "default_idf": 1.0}
    rec = {"keywords": ["rare", "common"], "symbols": [], "roles": []}
    score_rare, _ = mod.score_file({"rare"}, "x/file.py", rec, idf)
    score_common, _ = mod.score_file({"common"}, "x/file.py", rec, idf)
    assert score_rare > score_common, (score_rare, score_common)


def test_unknown_query_token_falls_back_to_default_idf():
    mod = _load_skill()
    idf = {"tokens": {"known": 3.0}, "default_idf": 0.7}
    rec = {"keywords": ["known", "mystery"], "symbols": [], "roles": []}
    score_known, _ = mod.score_file({"known"}, "x/file.py", rec, idf)
    score_unknown, _ = mod.score_file({"mystery"}, "x/file.py", rec, idf)
    # 'mystery' is absent from the table -> scored at default_idf (0.7), not
    # dropped (score 0) and not weighted at a bare 1.0.
    assert score_unknown == pytest_approx(2 * 0.7)
    assert score_known == pytest_approx(2 * 3.0)


def pytest_approx(x):
    import pytest
    return pytest.approx(x)


def test_no_hardcoded_stop_word_list_participates_in_scoring():
    """AC-9: static check: neither `score_file` nor `_module_signal` (nor the
    `_file_signal` helper feeding `score_file`) consults `_STOP_TOKENS` in
    its own body — down-weighting comes only from the IDF artifact lookup.
    `_STOP_TOKENS` may still exist for TOKENIZATION (deciding which query
    words are even candidate tokens at all) — that is a different concern
    from weighting a token once matched."""
    mod = _load_skill()
    for fn in (mod.score_file, mod._module_signal, mod._file_signal):
        src = inspect.getsource(fn)
        assert "_STOP_TOKENS" not in src, f"{fn.__name__} consults _STOP_TOKENS"
