"""run_signal.py — parse + retry-decision helpers for the `/klc:run`
orchestrator (KLC-052).

The orchestration loop itself lives in `klc-plugin/skills/run/SKILL.md`
as main-loop/Task-tool instructions (C-001: no Python loop driver —
decisions come from `phase_resolver` + `phases.yml` + this module, not
from a hidden imperative driver the plugin can't see). This module is
the one piece of that loop's decision logic that is pure enough to
unit test directly: parsing the structured completion signal (AC-3)
and the retry-once-then-stop policy (AC-6).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


REQUIRED_KEYS = ("phase", "signal", "artifacts", "blocking_questions", "next_action")
VALID_SIGNALS = {"done", "blocked", "failed"}
VALID_NEXT_ACTIONS = {"ack", "clarify", "stop"}

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


@dataclass
class Signal:
    phase:              str
    signal:             str
    artifacts:          list[str]
    blocking_questions: list[str]
    next_action:        str
    tokens:             dict | None = None


def _last_json_fence(text: str) -> str | None:
    """Return the contents of the LAST fenced code block in `text`, or
    None if there is none. The signal contract requires it be the
    final block in the agent's output."""
    matches = _FENCE_RE.findall(text)
    return matches[-1] if matches else None


def parse_signal(text: str, expected_phase: str) -> Signal | None:
    """Parse the AC-3 structured completion signal out of an agent's
    raw output.

    Returns None (→ orchestrator retry path, AC-6) when: no fenced
    block, invalid JSON, a required key is missing, `phase` doesn't
    match `expected_phase`, or `signal`/`next_action` isn't one of the
    allowed values. A `next_action` naming a nonexistent phase is not
    validated here — that is a routing concern, not a parse concern.
    """
    block = _last_json_fence(text)
    if block is None:
        return None
    try:
        obj = json.loads(block)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if any(k not in obj for k in REQUIRED_KEYS):
        return None
    if obj["phase"] != expected_phase:
        return None
    if obj["signal"] not in VALID_SIGNALS:
        return None
    if obj["next_action"] not in VALID_NEXT_ACTIONS:
        return None
    if not isinstance(obj["artifacts"], list) or not isinstance(obj["blocking_questions"], list):
        return None

    blocking = [q for q in obj["blocking_questions"] if isinstance(q, str) and q.strip()]
    return Signal(
        phase=obj["phase"],
        signal=obj["signal"],
        artifacts=list(obj["artifacts"]),
        blocking_questions=blocking,
        next_action=obj["next_action"],
        tokens=obj.get("tokens"),
    )


def should_retry(failure_count: int) -> bool:
    """AC-6: retry the same phase once on a dead/unparseable/mismatched
    signal; a second consecutive failure stops the loop.

    `failure_count` is the number of consecutive failures observed so
    far for the current phase (1 = first failure just happened).
    """
    return failure_count < 2
