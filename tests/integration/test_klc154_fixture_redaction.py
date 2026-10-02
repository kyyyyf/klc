"""tests/integration/test_klc154_fixture_redaction.py — KLC-154 step-3,
AC-14: every committed file under `tests/fixtures/klc154-corpus` yields no
hit from `_klc133_support.forbidden_hits` (the generic patterns plus the
KLC-165 private-term loader), after first proving the gate fires on a
seeded leak.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc133_support  # noqa: E402
import _klc154_support as support  # noqa: E402


def test_corpus_is_clean_after_gate_fires_on_seeded_leak(monkeypatch) -> None:
    """AC-14: the shared gate still fires on a seeded leak before the
    corpus trusts it, and no committed corpus file carries a hit."""
    monkeypatch.setenv(_klc133_support.REDACT_TERMS_ENV, ",ZYXQUORP,, ")
    leak = "See /tmp/scratch/file.py -- zyxquorp uses an @ character here."
    hits = _klc133_support.forbidden_hits(leak)
    assert hits, "the gate did not fire on a seeded leak"

    monkeypatch.delenv(_klc133_support.REDACT_TERMS_ENV, raising=False)
    files = [p for p in support.CORPUS.iterdir() if p.is_file()]
    assert files, "the corpus is empty"
    for path in files:
        text = path.read_text(encoding="utf-8")
        corpus_hits = _klc133_support.forbidden_hits(text)
        assert corpus_hits == [], f"{path.name}: {corpus_hits}"
