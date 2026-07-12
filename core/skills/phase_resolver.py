"""phase_resolver.py — the single phase→agent source of truth.

Both the interactive (main-loop/Task-tool) and headless (runner.py)
orchestration paths must derive the same dispatch decision — same
prompt, same model, same agent, same runs_inline flag — from the same
inputs: `phases.yml`, `models.yml`, the generated `klc-plugin/agents/`
set, and `meta.json:track`. This module is that single derivation.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_skills_dir = Path(__file__).resolve().parent
_project_root = _skills_dir.parent.parent
sys.path.insert(0, str(_skills_dir))
sys.path.insert(0, str(_project_root))

import lifecycle as _lc  # noqa: E402
import phases as _phases  # noqa: E402
import models as _models  # noqa: E402
import plugin_gen as _plugin_gen  # noqa: E402
from core.shared.paths import framework_root  # noqa: E402

@dataclass
class ResolvedPhase:
    phase_id:    str
    track:       str
    prompt_path: str | None
    model:       str
    cc_model:    str
    agent_type:  str | None
    runs_inline: bool
    interactive: bool


def _is_interactive(meta: dict, phase: "_phases.Phase") -> bool:
    # `intake-triage` is an agent invoked from within the `intake` phase
    # when routing confidence is low (KLC-052 step-4/6) — not a distinct
    # phases.yml id. The interactive signal lives on meta, not the phase.
    return bool(meta.get("clarify_required")) and phase.id == "intake"


def resolve_phase(ticket: str, phase_id: str) -> ResolvedPhase:
    """Resolve everything an executor needs to dispatch `phase_id` for
    `ticket`: prompt, model (raw + CC alias), agent type, whether it
    runs inline (XS fast-track) or via a subagent, and whether it is
    an interactive phase that headless runners must park on."""
    meta = _lc.read_meta(ticket)
    track = meta["track"]

    ph = _phases.load_phases()
    phase = ph.by_id(phase_id)

    resolved_model = _models.load_models().resolve(phase_id, track=track)
    model = resolved_model.model
    cc_model = _plugin_gen.cc_alias(model)

    # The agent file is named after phase.prompt's stem, NOT phase_id —
    # several phases share one agent (build -> impl.md, manual ->
    # manual-check.md, learn -> retrospective.md, acceptance-test-plan /
    # detailed-test-plan -> test-planner.md). Phases with no prompt
    # (intake, integrate, observe) have no dispatch agent at all.
    prompt_stem = Path(phase.prompt).stem if phase.prompt else None
    agent_md = (
        framework_root() / "klc-plugin" / "agents" / f"{prompt_stem}.md"
        if prompt_stem else None
    )
    agent_type = f"klc-{prompt_stem}" if agent_md and agent_md.exists() else None

    runs_inline = track == "XS" and phase in ph.track_phases("XS")

    return ResolvedPhase(
        phase_id=phase_id,
        track=track,
        prompt_path=phase.prompt or None,
        model=model,
        cc_model=cc_model,
        agent_type=agent_type,
        runs_inline=runs_inline,
        interactive=_is_interactive(meta, phase),
    )
