#!/usr/bin/env python3
"""KLC-107 step-12 — README.md describes verb-guaranteed freshness and the
optional hook accelerator (AC-29, spec C-007)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"


def test_readme_describes_verb_guaranteed_freshness_and_optional_hook():
    """AC-29: README describes the code's actual install/refresh behaviour."""
    text = README.read_text(encoding="utf-8")

    # The old FACT-cited sentences (spec.md README.md:9,50) must be gone
    # verbatim.
    assert "Runs automatically via the pre-commit hook after each commit." not in text
    assert "wires the pre-commit hook" not in text

    # The install and indexing-loop sections state the new contract.
    assert "guaranteed by the lifecycle verbs" in text
    assert "optional accelerator" in text
    assert "no other hook manager owns" in text or "no other manager owns" in text
    assert "--no-index-refresh" in text
    assert "klc doctor" in text


if __name__ == "__main__":
    import unittest
    unittest.main()
