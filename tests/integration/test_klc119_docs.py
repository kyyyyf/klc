#!/usr/bin/env python3
"""KLC-119 step-8 — AC-15: the process documentation states which `source`
each dispatch path can realistically produce, naming the Claude Code Task
path as `estimated`-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]


def test_docs_process_md_states_task_dispatch_path_is_estimated_only_and_names_signal_as_forward_compatible():
    """AC-15: the process documentation states which `source` each dispatch
    path can realistically produce, naming the interactive Claude Code Task
    path as `estimated`-only and `signal` as a forward-compatible channel."""
    text = (FW_ROOT / "docs" / "process.md").read_text(encoding="utf-8")
    assert "estimated`-only" in text, \
        "the interactive Task dispatch path must be named estimated-only"
    assert "forward-compatible channel" in text
    assert "zero" in text and "signal" in text


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
