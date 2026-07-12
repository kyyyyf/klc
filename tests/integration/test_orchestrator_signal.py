"""KLC-052 step-7: run_signal.parse_signal — the AC-3 structured
completion signal contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import run_signal  # noqa: E402


_VALID_TEXT = """
Some prose the agent wrote about what it did.

```json
{"phase":"design","signal":"done","artifacts":["design/options.md","impl-plan.md"],"blocking_questions":[],"next_action":"ack"}
```
"""


def test_structured_signal_parsed_correctly():
    sig = run_signal.parse_signal(_VALID_TEXT, expected_phase="design")
    assert sig is not None
    assert sig.phase == "design"
    assert sig.signal == "done"
    assert sig.artifacts == ["design/options.md", "impl-plan.md"]
    assert sig.blocking_questions == []
    assert sig.next_action == "ack"


def test_takes_last_fenced_block_when_multiple_present():
    text = (
        "```json\n{\"not\":\"this one\"}\n```\n"
        "more prose\n"
        "```json\n"
        '{"phase":"build","signal":"done","artifacts":[],'
        '"blocking_questions":[],"next_action":"ack"}\n'
        "```\n"
    )
    sig = run_signal.parse_signal(text, expected_phase="build")
    assert sig is not None
    assert sig.phase == "build"


def test_phase_mismatch_returns_none():
    sig = run_signal.parse_signal(_VALID_TEXT, expected_phase="build")
    assert sig is None


def test_missing_required_key_returns_none():
    text = '```json\n{"phase":"design","signal":"done","artifacts":[]}\n```\n'
    assert run_signal.parse_signal(text, expected_phase="design") is None


def test_invalid_signal_enum_returns_none():
    text = (
        '```json\n{"phase":"design","signal":"maybe","artifacts":[],'
        '"blocking_questions":[],"next_action":"ack"}\n```\n'
    )
    assert run_signal.parse_signal(text, expected_phase="design") is None


def test_unparseable_json_returns_none():
    text = "```json\nnot json at all {{{\n```\n"
    assert run_signal.parse_signal(text, expected_phase="design") is None


def test_no_fenced_block_returns_none():
    assert run_signal.parse_signal("just prose, no JSON", expected_phase="design") is None


def test_blank_blocking_questions_are_ignored():
    text = (
        '```json\n{"phase":"design","signal":"done","artifacts":[],'
        '"blocking_questions":["  ", "", "real question?"],"next_action":"ack"}\n```\n'
    )
    sig = run_signal.parse_signal(text, expected_phase="design")
    assert sig is not None
    assert sig.blocking_questions == ["real question?"]
