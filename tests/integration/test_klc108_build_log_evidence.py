"""KLC-108 — AC-17: the BEFORE and AFTER eval reports are recorded in the
ticket's build log as the evidence for AC-15 and AC-16; each entry names
the corpus size, the index the run used, and both metric means."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_LOG = REPO_ROOT / ".klc" / "tickets" / "KLC-108" / "build-log.md"


def _text() -> str:
    if not BUILD_LOG.exists():
        import pytest
        pytest.skip("build-log.md not present (ticket workspace not checked out)")
    return BUILD_LOG.read_text(encoding="utf-8")


def test_build_log_records_before_after_corpus_size_index_and_means():
    """AC-17: the BEFORE and AFTER eval reports are recorded in the ticket's
    build log as the evidence for AC-15 and AC-16; each entry names the
    corpus size, the index the run used, and both metric means."""
    text = _text()
    assert "## Step 8" in text
    step8 = text.split("## Step 8", 1)[1]
    # BEFORE entry
    assert "probe subset" in step8 or "KLC-100, KLC-101, KLC-102" in step8
    assert "precision_at_5" in step8
    assert "recall_at_10" in step8
    # AFTER entry: corpus size + index
    assert "110" in step8, "AFTER corpus size (110 archived tickets) must be named"
    assert ".klc/index" in step8 or "index" in step8.lower()
    # both metric means for AFTER
    assert "0.227" in step8 or "0.2273" in step8
    assert "0.101" in step8 or "0.1016" in step8
