"""KLC-111 step-8 — the operator index-rebuild step is reproducible from the
documentation alone, without reading this ticket (AC-17).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_docs_record_klc_init_scan_only_and_klc_state_commit_step_verbatim():
    """AC-17: `docs/` records the operator index-rebuild step with the
    literal command `klc init --scan-only` and describes the klc-state
    commit that replaces the 29-name file — reproducible from the docs
    alone."""
    process_text = (REPO / "docs" / "process.md").read_text(encoding="utf-8")
    assert "klc init --scan-only" in process_text, (
        "docs/process.md must record the literal rebuild command")
    assert "29-name" in process_text, (
        "docs/process.md must describe the klc-state commit that replaces "
        "the 29-name file")
    assert "--migrate-vocabulary" in process_text

    arch_text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "scope.infra_paths" in arch_text
    assert "module_vocabulary" in arch_text

    readme_text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "migrate-vocabulary" in readme_text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
