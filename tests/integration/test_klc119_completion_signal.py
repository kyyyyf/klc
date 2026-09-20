#!/usr/bin/env python3
"""KLC-119 step-6 — AC-13: the shared completion-signal include asks for
`tokens` only when the host exposes usage to the agent; an absent field is
normal and klc falls back to the card estimate.

Step-9 (review-fix round 1, MEDIUM #1 / AC-13): the byte-neutral rewording
dropped the `(orchestrator)` disambiguator from the include's heading and
the "as the LAST output block" qualifier from the JSON-signal sentence.
Several role prompts already carry an older, unrelated `## Completion
signal` section (a legacy plain-stdout marker) ABOVE the include's own
expansion, so once the include's heading loses its disambiguator, a
generated agent file ends up with two identically-titled `## Completion
signal` headings and no textual cue for which one is authoritative —
exactly the ambiguity `run_signal.parse_signal` depends on the agent
resolving correctly (it takes only the LAST fenced JSON block).
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
INCLUDE = FW_ROOT / "core" / "agents" / "_includes" / "completion-signal.md"
GENERATED_AGENTS_DIR = FW_ROOT / "klc-plugin" / "agents"


def test_completion_signal_include_asks_for_tokens_only_when_host_exposes_usage_to_the_agent():
    text = INCLUDE.read_text(encoding="utf-8")
    assert "ONLY if your host shows you your usage" in text, \
        "the include must state the host condition, not ask unconditionally"
    assert "absent is normal" in text
    assert "estimates from the card" in text


def test_completion_signal_include_keeps_the_orchestrator_disambiguator_and_last_block_wording():
    """AC-13 review-fix (MEDIUM #1): the heading must stay distinguishable
    from the legacy plain-stdout `## Completion signal` section some role
    prompts already carry, and the LAST-output-block guarantee — the plain
    language backing `_last_json_fence`'s last-fenced-block assumption —
    must not be silently dropped by a future byte trim."""
    text = INCLUDE.read_text(encoding="utf-8")
    assert "## Completion signal (orchestrator)" in text, \
        "the heading must keep its disambiguator, or a legacy stdout-marker " \
        "section elsewhere in the same generated agent becomes indistinguishable"
    assert "as the LAST output block" in text, \
        "the JSON-signal instruction must keep the explicit LAST-output-block " \
        "qualifier — the textual guarantee behind _last_json_fence"


def test_no_generated_agent_has_two_identically_titled_completion_signal_headings():
    """No `klc-plugin/agents/*.md` file may contain the exact heading text
    `## Completion signal` more than once — a duplicate, unreconciled
    heading leaves a subagent with no cue for which section governs its
    actual completion signal."""
    offenders = {}
    for md in sorted(GENERATED_AGENTS_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        count = sum(1 for line in text.splitlines()
                   if line.strip() == "## Completion signal")
        if count > 1:
            offenders[md.name] = count
    assert offenders == {}, \
        f"generated agents with a duplicate '## Completion signal' heading: {offenders}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
