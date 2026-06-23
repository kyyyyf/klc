"""Prompt-regression harness for klc agent prompts.

Structural helpers (impl_plan_violations, has_min_approaches) run fully offline
with no API key.  The judge() helper calls the review model and requires an API
key — guard calls with judge_available().  Tests that depend on judge() use
monkeypatching or pytest.importorskip; all other tests are CI-safe.

Adding fixtures for a new phase:
  1. Write a test in tests/test_prompt_regression.py importing from this module.
  2. For prompt-gap sentinels use @pytest.mark.xfail(strict=True) so the suite
     fails loudly when the gap is closed but the sentinel is not removed.
"""
from __future__ import annotations
import os
import re
import sys
import tempfile
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_FW_ROOT))
from core.skills.runner import run_agent  # noqa: E402

from core.skills.spec_selfreview import PLACEHOLDER_TOKENS  # noqa: E402
from core.skills.spec_structure import has_min_approaches  # noqa: E402
REQUIRED_STEP_FIELDS = (
    "Goal", "VERIFY", "COMMIT", "Affected", "Interfaces", "Expected", "Code sketch"
)

_NOT_APPLICABLE_RE = re.compile(r"(?i)\bred:.*not applicable")
_CODE_FENCE_RE = re.compile(r"```[a-z]*\n([\s\S]+?)```")


def _has_code_sketch(body: str) -> bool:
    """True when body has a non-empty fenced code block (empty ``` ``` does not count)."""
    m = _CODE_FENCE_RE.search(body)
    return m is not None and bool(m.group(1).strip())


def parse_impl_plan_steps(text: str) -> list[dict]:
    """Split an impl-plan markdown into steps keyed by '## step-N — title'."""
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
    """Return human-readable violations in an impl-plan."""
    steps = parse_impl_plan_steps(text)
    if not steps:
        return ["no steps found in impl-plan"]

    violations: list[str] = []
    for step in steps:
        body = step["body"]
        sid = step["id"]

        _not_applicable = _NOT_APPLICABLE_RE.search(body)
        for field in REQUIRED_STEP_FIELDS:
            # Code sketch is exempt for prompt/doc/config steps (RED: not applicable)
            if field == "Code sketch" and _not_applicable:
                continue
            pattern = re.compile(
                rf"(?im)(?:\*\*{re.escape(field)}\b|\b{re.escape(field)}:)"
            )
            if not pattern.search(body):
                violations.append(f"{sid}: missing required field '{field}'")

        for token in PLACEHOLDER_TOKENS:
            if token == "...":
                if re.search(r"(?<![\w.])\.\.\.(?![\w.])", body):
                    violations.append(f"{sid}: contains placeholder token '...'")
            else:
                if token in body:
                    violations.append(f"{sid}: contains placeholder token '{token}'")

        if re.search(r"```[a-z]*\s*```", body):
            violations.append(f"{sid}: contains empty code fence")

        # require a non-empty code sketch unless the step is prompt/doc/config only
        if not _not_applicable:
            if not _has_code_sketch(body):
                violations.append(
                    f"{sid}: missing code sketch (add a non-empty fenced block, "
                    "or mark 'RED: not applicable' for prompt/doc/config steps)"
                )

    return violations


def _judge_api_key_env() -> str:
    """Resolve the judge model's api_key_env via models.resolve('review')."""
    from core.skills.models import load_models
    return load_models().resolve("review").api_key_env or "ANTHROPIC_API_KEY"


def judge_available() -> bool:
    return bool(os.environ.get(_judge_api_key_env()))


def judge(output: str, rubric: str) -> dict:
    """Ask the judge model whether output satisfies rubric.

    Returns {"pass": bool, "reason": str}. When the API key is unset,
    calls pytest.skip() so the calling test is skipped gracefully (AC-2).
    """
    if not judge_available():
        import pytest as _pytest
        _pytest.skip(f"judge API key ({_judge_api_key_env()}) not set")

    prompt = (
        f"{rubric}\n\n"
        "---\n"
        "Agent output to evaluate:\n\n"
        f"{output}\n\n"
        "---\n"
        "Reply with a single line in one of these forms:\n"
        "  PASS: <brief reason>\n"
        "  FAIL: <brief reason>\n"
    )
    with (
        tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as pf,
        tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as of,
    ):
        pf.write(prompt)
        prompt_path = Path(pf.name)
        out_path = Path(of.name)

    try:
        rc = run_agent(phase_id="review", prompt_path=prompt_path, out_path=out_path, track="S")
        if rc != 0:
            raise RuntimeError(f"run_agent dispatch failed (exit {rc})")
        raw = out_path.read_text(encoding="utf-8").strip()
    finally:
        prompt_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

    if raw.upper().startswith("PASS"):
        return {"pass": True, "reason": raw.split(":", 1)[-1].strip()}
    return {"pass": False, "reason": raw.split(":", 1)[-1].strip() if ":" in raw else raw}

