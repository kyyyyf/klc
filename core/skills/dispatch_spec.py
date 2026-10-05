#!/usr/bin/env python3
"""dispatch_spec.py — what the in-client orchestrator needs to start a phase agent.

`dispatch_spec(ticket, phase)` answers with the agent type, the Claude Code model
alias and the card path. The alias comes from models.yml for the ticket's TRACK
(`per_track` wins over `phase_roles`), so an XS review and an M review can run on
different models.

Why the model is passed explicitly: the generated agent files carry a frontmatter
`model:`, but whether Claude Code honours it for a Task dispatch is unconfirmed.
`Task(model=...)` removes the question, so `klc go` prints the alias next to the
card and the orchestrator copies it.

CLI: `python3 core/skills/dispatch_spec.py KEY PHASE` prints the JSON (or `null`
for a phase that has no agent).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_resolver as _pr  # noqa: E402


def dispatch_spec(ticket: str, phase: str) -> dict | None:
    """`{agent_type, model, card}` for a Task dispatch, or None without an agent."""
    r = _pr.resolve_phase(ticket, phase, executor=_pr.EXECUTOR_TASK)
    if not r.agent_type:
        return None
    return {"agent_type": r.agent_type, "model": r.cc_model, "card": r.card_path}


def dispatch_line(ticket: str, phase: str) -> str:
    """The machine-readable stop line, or "" when the phase has no agent."""
    try:
        spec = dispatch_spec(ticket, phase)
    except Exception:
        return ""
    if not spec:
        return ""
    return (f"dispatch: agent={spec['agent_type']} model={spec['model']} "
            f"card={spec['card']}")


if __name__ == "__main__":
    print(json.dumps(dispatch_spec(sys.argv[1], sys.argv[2])))
