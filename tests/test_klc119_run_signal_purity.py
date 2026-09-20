#!/usr/bin/env python3
"""KLC-119 step-5 — C-007: `run_signal.parse_signal` stays a pure parser
with no filesystem side effect; `record_signal_tokens` is a separate
caller, never folded into the parser itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import run_signal  # noqa: E402


def test_parse_signal_has_no_filesystem_side_effect_on_a_tmp_cwd_with_no_ticket(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROJECT_ROOT", raising=False)
    before = sorted(str(p) for p in tmp_path.rglob("*"))

    text = ('```json\n{"phase":"build","signal":"done","artifacts":[],'
           '"blocking_questions":[],"next_action":"ack",'
           '"tokens":{"in":10,"out":2}}\n```')
    result = run_signal.parse_signal(text, "build")

    assert result is not None
    assert result.tokens == {"in": 10, "out": 2}
    after = sorted(str(p) for p in tmp_path.rglob("*"))
    assert before == after, \
        "parse_signal must create/modify no file — the recorder is a sibling"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
