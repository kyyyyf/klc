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

PLACEHOLDER_TOKENS = ("TODO", "TBD", "write tests", "<...>", "...")
REQUIRED_STEP_FIELDS = ("Goal", "VERIFY", "COMMIT", "Affected")


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

        for field in REQUIRED_STEP_FIELDS:
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

    return violations


def _judge_api_key_env() -> str:
    """Resolve the judge model's api_key_env via models.resolve('review')."""
    from core.skills.models import load_models
    return load_models().resolve("review").api_key_env or "ANTHROPIC_API_KEY"


def judge_available() -> bool:
    return bool(os.environ.get(_judge_api_key_env()))


def judge(output: str, rubric: str) -> dict:
    """Ask the judge model whether output satisfies rubric.

    Returns {"pass": bool, "reason": str}. Caller must guard with
    judge_available() — raises RuntimeError if key missing.
    """
    if not judge_available():
        raise RuntimeError("Judge API key not set; check judge_available() first")

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


def has_min_approaches(text: str, n: int = 2) -> bool:
    """True iff the text proposes >= n distinct approaches."""
    line_pattern = re.compile(
        r"(?im)^(\s*(?:[-*]|\d+\.|#{2,3})\s*(?:option|approach|approach\s+\d|alternative)\b[^\n]*)"
    )
    matches = line_pattern.findall(text)
    normalized = {m.strip().lower() for m in matches}
    return len(normalized) >= n
