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
from core.skills.impl_plan_check import (  # noqa: E402
    REQUIRED_STEP_FIELDS,
    _red_not_applicable,
    _CODE_FENCE_RE,
    _has_code_sketch,
    parse_impl_plan_steps,
    impl_plan_violations,
)


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

