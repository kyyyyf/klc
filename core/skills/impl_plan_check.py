"""impl_plan_check.py — shared impl-plan parser and violation detector.

Single source of truth for step-field enforcement; imported by both
tests/prompt_harness.py (offline harness) and core/skills/phase_completion.py
(gate at discovery-lite S and design M/L ack).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow standalone import and use from tests/ (project root not always in path)
_SKILLS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SKILLS_DIR.parent.parent
for _p in (str(_PROJECT_ROOT), str(_SKILLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spec_selfreview import PLACEHOLDER_TOKENS  # noqa: E402

REQUIRED_STEP_FIELDS = (
    "Goal", "VERIFY", "COMMIT", "Affected", "Interfaces", "Expected", "Code sketch"
)

# RED-marker parser kept in lock-step with phase_completion.py:413 (commit
# 9069f1f), STRUCTURE and all: match the FIRST `RED:` line only and test its
# captured remainder for "not applicable" — never a whole-body `.*` scan (which
# would let an unrelated prose line reading "…red: … not applicable" wrongly
# exempt a genuine-RED step). `\**` tolerates markdown emphasis between `RED` and
# the colon, so `RED:`, `**RED:**` and `**RED**:` all parse identically.
_RED_LINE_RE = re.compile(r"(?i)\bRED\**:(.+)")


def _red_not_applicable(body: str) -> bool:
    """True iff the FIRST `RED:` line marks the step as not applicable."""
    m = _RED_LINE_RE.search(body)
    return bool(m and "not applicable" in m.group(1).lower())
_CODE_FENCE_RE = re.compile(r"```[a-z]*\n([\s\S]+?)```")
_ANY_FENCE_RE = re.compile(r"```[^\n]*\n[\s\S]*?```")


def _has_code_sketch(body: str) -> bool:
    """True when body contains a non-empty fenced block."""
    m = _CODE_FENCE_RE.search(body)
    return m is not None and bool(m.group(1).strip())


def parse_impl_plan_steps(text: str) -> list[dict]:
    """Split impl-plan markdown into steps keyed by '## step-N — title'."""
    pattern = re.compile(r"(?m)^##\s+(step-\d+)\s*[—-]\s*(.+)$")
    matches = list(pattern.finditer(text))
    steps = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        steps.append({
            "id": m.group(1),
            "title": m.group(2).strip(),
            "body": text[start:end],
        })
    return steps


def impl_plan_violations(text: str) -> list[str]:
    """Return human-readable violations found in an impl-plan."""
    steps = parse_impl_plan_steps(text)
    if not steps:
        return ["no steps found in impl-plan"]

    violations: list[str] = []
    for step in steps:
        body = step["body"]
        sid = step["id"]

        # Strip fenced blocks before field and placeholder detection so that
        # content inside code sketches (e.g. # Code sketch: or TODO) does not
        # falsely satisfy or trigger checks.
        body_outside_fences = _ANY_FENCE_RE.sub("", body)
        _not_applicable = _red_not_applicable(body_outside_fences)
        for field in REQUIRED_STEP_FIELDS:
            if field == "Code sketch" and _not_applicable:
                continue
            pattern = re.compile(
                rf"(?im)(?:\*\*{re.escape(field)}\b|\b{re.escape(field)}:)"
            )
            if not pattern.search(body_outside_fences):
                violations.append(f"{sid}: missing required field '{field}'")
        for token in PLACEHOLDER_TOKENS:
            if token == "...":
                if re.search(r"(?<![\w.])\.\.\.(?![\w.])", body_outside_fences):
                    violations.append(f"{sid}: contains placeholder token '...'")
            else:
                if token in body_outside_fences:
                    violations.append(f"{sid}: contains placeholder token '{token}'")

        if re.search(r"```[a-z]*\s*```", body):
            violations.append(f"{sid}: contains empty code fence")

        if not _not_applicable:
            if not _has_code_sketch(body):
                violations.append(
                    f"{sid}: missing code sketch (add a non-empty fenced block, "
                    "or mark 'RED: not applicable' for prompt/doc/config steps)"
                )

    return violations
