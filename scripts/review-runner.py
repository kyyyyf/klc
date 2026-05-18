#!/usr/bin/env python3
"""review-runner.py — fulfil a review sub-agent job card via the
configured model.

Replaces scripts/review-runner-claude.sh. Reads `config/models.yml`
(through `core/skills/runner.py`), resolves the model for role
`review-internal` (or `review-external` for the external reviewer),
and dispatches.

Contract with review.sh / review.py:
  - Called with two positional args: <job-card-path> <partial-out-path>.
  - Reads the job card's `Prompt file:` and `Inputs:` lines to find the
    prompt + inputs (diff, spec, claude_md_context, allowlist).
  - Writes the sub-agent's output to the partial path.
  - The script MUST NOT print anything to stdout besides fatal errors.

Cross-platform (Python-only; no bash).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
from runner import run_agent  # noqa: E402


_FIELD_RE = re.compile(r"^(Prompt file|- diff|- spec|- claude_md_context|- allowlist):\s*(.+)$")


def _parse_job_card(card: Path) -> dict[str, str]:
    """Pull the labelled fields out of the job card. Returns a dict
    keyed by 'prompt', 'diff', 'spec', 'context', 'allowlist'."""
    out: dict[str, str] = {}
    mapping = {
        "Prompt file":       "prompt",
        "- diff":            "diff",
        "- spec":            "spec",
        "- claude_md_context": "context",
        "- allowlist":       "allowlist",
    }
    for line in card.read_text(encoding="utf-8").splitlines():
        m = _FIELD_RE.match(line.rstrip())
        if m:
            key = mapping.get(m.group(1))
            if key and key not in out:
                out[key] = m.group(2).strip()
    return out


def _role_for(prompt_path: Path) -> str:
    """Sub-agents under core/agents/review/ are internal; the sole
    external reviewer lives at core/agents/external-review.md."""
    if prompt_path.name == "external-review.md":
        return "review-external"
    return "review-internal"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: review-runner.py <job-card> <partial-out>\n")
        return 2
    card_path = Path(argv[0])
    partial_path = Path(argv[1])
    if not card_path.is_file():
        sys.stderr.write(f"review-runner: job card not found: {card_path}\n")
        return 2

    fields = _parse_job_card(card_path)
    prompt = fields.get("prompt")
    if not prompt:
        sys.stderr.write(f"review-runner: job card missing 'Prompt file': {card_path}\n")
        return 2
    prompt_path = Path(prompt)
    if not prompt_path.is_absolute():
        prompt_path = FRAMEWORK_ROOT / prompt_path

    inputs: dict[str, Path | str] = {}
    for label in ("diff", "spec", "context", "allowlist"):
        val = fields.get(label)
        if not val:
            continue
        p = Path(val)
        if p.is_file():
            inputs[label] = p

    # `review-internal` and `review-external` are pseudo-phases in
    # models.yml::phase_roles. The runner accepts them verbatim.
    phase_id = _role_for(prompt_path)

    # Track hint: look in meta.json next to spec if we can find it.
    track = _infer_track_from_spec(inputs.get("spec"))

    return run_agent(
        phase_id=phase_id,
        prompt_path=prompt_path,
        out_path=partial_path,
        inputs=inputs,
        track=track,
    )


def _infer_track_from_spec(spec_path: object) -> str | None:
    """If the spec lives inside a ticket dir, read meta.json:track.
    Returns None on any miss."""
    if not isinstance(spec_path, Path):
        return None
    meta = spec_path.parent / "meta.json"
    if not meta.exists():
        return None
    try:
        import json
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    track = data.get("track")
    if track in ("XS", "S", "M", "L"):
        return track
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
