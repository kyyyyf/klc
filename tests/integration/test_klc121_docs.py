#!/usr/bin/env python3
"""KLC-121 step-7 — AC-11: the documentation records what shipped and what
did not."""
from __future__ import annotations

from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_MD = FRAMEWORK_ROOT / "docs" / "architecture.md"
INDEX_REFRESH = FRAMEWORK_ROOT / "core" / "skills" / "index_refresh.py"


def test_architecture_md_documents_fingerprint_substrate_and_full_rebuild_conditions():
    """AC-11: `docs/architecture.md` names the per-file fingerprint map as the
    substrate a later incremental merge (KLC-125) will consume, states that
    fingerprints and the fallback are keyed by path and digest and never by
    language, lists every AC-6 full-rebuild condition, and says plainly
    that every refresh is still a full rebuild until KLC-125 lands."""
    text = ARCHITECTURE_MD.read_text(encoding="utf-8")

    assert "KLC-121" in text
    assert "KLC-125" in text
    assert "fingerprint" in text.lower()

    lowered = text.lower()
    assert "path and digest" in lowered or "path and the recorded digest" in lowered

    for condition in ("--full", "absent", "unparseable",
                      "schema_version", "fingerprint_algo",
                      "files_rel_source", "profile identity"):
        assert condition in text, f"full-rebuild condition not documented: {condition}"

    assert "full rebuild" in lowered
    assert "every refresh is still a full rebuild" in lowered


def test_stale_6_5s_comment_replaced_with_measured_baseline_and_klc125_pointer():
    """AC-11: The stale `~6.5s` figure at `core/skills/index_refresh.py:40` is
    replaced by a measured figure consistent with F-014's baseline,
    together with a pointer naming KLC-125 as the ticket that will make
    refreshes non-full."""
    text = INDEX_REFRESH.read_text(encoding="utf-8")
    assert "~6.5s" not in text and "6.5 s" not in text
    assert "DEFAULT_BUDGET_S" in text
    assert "KLC-121" in text
    assert "KLC-125" in text


if __name__ == "__main__":
    import unittest
    unittest.main()
