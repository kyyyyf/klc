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
    prompt + inputs (context, spec).
  - Writes the sub-agent's output to the partial path.
  - The script MUST NOT print anything to stdout besides fatal errors.

KLC-133 AC-5: this script writes no telemetry attempt of its own — it
delegates the ticket, the "review" tag phase, the reviewer name, and the
job card's byte size to `run_agent`, which reads the CLI's own provider
usage block when the dispatch returns one (`source="provider"`). Since
KLC-174 there is no `estimated` fallback: a dispatch without usage records
nothing.

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


_FIELD_RE = re.compile(r"^(Prompt file|- spec|- context|- adr_context|Addendum):\s*(.+)$")
_ADDENDUM_MAX = 1024


def _parse_job_card(card: Path) -> dict[str, str]:
    """Pull the labelled fields out of the job card. Returns a dict keyed by
    'prompt', 'spec', 'context', 'adr_context' and 'addendum'. KLC-175: the card names
    `context.md` once; the diff, the rubric and the allowlist are not separate
    inputs (and CLAUDE.md and the rule catalog are never inlined)."""
    out: dict[str, str] = {}
    mapping = {
        "Prompt file":  "prompt",
        "- spec":       "spec",
        "- context":    "context",
        "- adr_context": "adr_context",
        "Addendum":     "addendum",
    }
    for line in card.read_text(encoding="utf-8").splitlines():
        m = _FIELD_RE.match(line.rstrip())
        if m:
            key = mapping.get(m.group(1))
            if key and key not in out:
                out[key] = m.group(2).strip()
    return out


def _build_inputs(fields: dict[str, str]) -> dict[str, Path | str]:
    """What a headless dispatch inlines. A headless model cannot read by path,
    so `context.md` (the whole shared context) is inlined ONCE per card; the
    spec path is only used to find the ticket and track. The card's addendum
    (at most 1 KB: the reviewer's file filter and focus) follows as a text
    block: a headless specialist gets its filter as an INSTRUCTION, not as a
    filtered diff (the full diff is in context.md)."""
    inputs: dict[str, Path | str] = {}
    for label in ("context", "adr_context"):
        val = fields.get(label)
        if val and Path(val).is_file():
            inputs[label] = Path(val)
    addendum = fields.get("addendum")
    if addendum:
        inputs["addendum"] = addendum.encode("utf-8")[:_ADDENDUM_MAX].decode("utf-8", "ignore")
    return inputs


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

    inputs = _build_inputs(fields)

    # `review-internal` and `review-external` are pseudo-phases in
    # models.yml::phase_roles. The runner accepts them verbatim.
    phase_id = _role_for(prompt_path)

    # Track hint: look in meta.json next to spec if we can find it.
    spec_path = Path(fields["spec"]) if fields.get("spec") else None
    track = _infer_track_from_spec(spec_path)

    ticket = _ticket_from_spec(spec_path)
    reviewer = partial_path.name.removesuffix(".partial.md")
    return run_agent(
        phase_id=phase_id,
        prompt_path=prompt_path,
        out_path=partial_path,
        inputs=inputs,
        track=track,
        telemetry_ticket=ticket,
        telemetry_phase="review",
        reviewer=reviewer,
        card_bytes=card_path.stat().st_size,
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


def _ticket_from_spec(spec_path: object) -> str | None:
    """KLC-120 D-008: the same "spec lives inside a ticket dir" lookup as
    `_infer_track_from_spec`, but for the ticket key rather than the track.
    Returns None on any miss (a headless run against a spec that isn't
    inside a real ticket dir records no attempt — write_token_metrics
    itself already no-ops on an empty ticket)."""
    if not isinstance(spec_path, Path):
        return None
    meta_path = spec_path.parent / "meta.json"
    if not meta_path.exists():
        return None
    try:
        import json
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ticket = data.get("ticket")
    if isinstance(ticket, str) and ticket:
        return ticket
    return spec_path.parent.name or None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
