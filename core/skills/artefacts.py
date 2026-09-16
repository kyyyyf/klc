#!/usr/bin/env python3
"""artefacts.py — prompt-card generation and per-ticket lock.

The phase scripts were deleted when klc became data-driven. The two
pieces they still owned — producing a copypaste-ready prompt for the
agent, and taking a lock so two terminals can't race on `next`/`ack` —
live here now.

Responsibilities:

  write_prompt_card(ticket, phase_id, meta, step=None)
      Render the prompt for a phase into
      `.klc/tickets/<ticket>/<phase>/_prompt.md`. Content:
        - a short preamble (ticket key, track, state, phase purpose)
        - the agent prompt body from phases.yml:work.prompt
        - pointers to relevant inputs (resolved from phase.inputs).
      For phases without a prompt (intake, observe), writes a
      checklist or pointer card instead. Returns the absolute path.
      When phase_id == "build" and step is given, renders the minimal
      impl-step.md.j2 card instead (only current step context).

  write_step_card(ticket, step, meta)
      Render `.klc/tickets/<ticket>/build/_prompt_step_N.md` for a
      specific TDD step. Uses impl-step.md.j2. Returns the path.

  acquire_lock(ticket)
      Context manager. Writes PID + ISO timestamp to
      `.klc/tickets/<ticket>/.lock`. Releases on exit. If a live lock
      exists with a different PID, raises LockedError.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root, klc_ticket_dir  # noqa: E402
import phases as _ph  # noqa: E402
from impl_plan_check import parse_impl_plan_steps, extract_step_fields  # noqa: E402


class LockedError(RuntimeError):
    pass


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- lock ---------------------------------------------------------------------

def _lock_path(ticket: str) -> Path:
    return klc_ticket_dir(ticket) / ".lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


@contextlib.contextmanager
def acquire_lock(ticket: str):
    """Acquire a per-ticket lock. Raises LockedError if a live process
    holds it; stale locks (owning PID no longer exists) are reclaimed."""
    lp = _lock_path(ticket)
    lp.parent.mkdir(parents=True, exist_ok=True)
    if lp.exists():
        try:
            rec = json.loads(lp.read_text(encoding="utf-8"))
            owner = int(rec.get("pid", 0))
        except (json.JSONDecodeError, ValueError):
            owner = 0
        if owner and owner != os.getpid() and _pid_alive(owner):
            raise LockedError(
                f"ticket {ticket!r} is locked by PID {owner} "
                f"(lock file: {lp}); wait or remove manually if stale"
            )
    lp.write_text(
        json.dumps({"pid": os.getpid(), "at": _now()}) + "\n",
        encoding="utf-8",
    )
    try:
        yield
    finally:
        try:
            lp.unlink()
        except OSError:
            pass


# --- prompt cards -------------------------------------------------------------

_PREAMBLE_TMPL = """\
# Agent prompt — {ticket} · {phase_id}:work

You are working in phase **{phase_id}**. Read the role prompt below,
then produce the outputs listed at the bottom. When you claim the
work is done, the human runs `klc ack {ticket}` (with `--pick N` if
required) to confirm.

"""

_INPUTS_TMPL = """
---

## Inputs you should read

{inputs_block}
"""

_OUTPUTS_TMPL = """
---

## Outputs the ack step will verify

{outputs_block}

## When done

{ack_instruction}
"""


def _format_inputs(ticket: str, phase: _ph.Phase) -> str:
    tdir = klc_ticket_dir(ticket)
    if not phase.inputs:
        return "_(none; this phase has no required inputs)_"
    lines = []
    for rel in phase.inputs:
        path = tdir / rel
        mark = "✓" if path.exists() else "✗"
        lines.append(f"- [{mark}] `.klc/tickets/{ticket}/{rel}`")
    return "\n".join(lines)


def _format_outputs(phase: _ph.Phase) -> str:
    if not phase.outputs:
        return "_(no fixed artefacts; update whatever the role prompt specifies)_"
    return "\n".join(f"- `.klc/tickets/<key>/{o}`" for o in phase.outputs)


def _format_ack_instruction(ticket: str, phase: _ph.Phase) -> str:
    if not phase.picks:
        return f"`klc ack {ticket}`"
    if len(phase.picks) == 1 and not phase.pick_required:
        return f"`klc ack {ticket}`"
    opts = "\n".join(f"  - `{pk.id}` = {pk.label}" for pk in phase.picks)
    return f"`klc ack {ticket} --pick <N>`, where N is:\n\n{opts}"


def write_prompt_card(ticket: str, phase_id: str, meta: dict,
                      step: int | None = None) -> Path:
    """Render `.klc/tickets/<ticket>/<phase>/_prompt.md`. Returns the path.

    When phase_id == "build" and step is given, delegates to
    write_step_card() which uses the minimal impl-step template.
    """
    if phase_id == "build" and step is not None:
        return write_step_card(ticket, step, meta)

    ph = _ph.load_phases()
    phase = ph.by_id(phase_id)
    tdir = klc_ticket_dir(ticket)
    phase_dir = tdir / phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    card = phase_dir / "_prompt.md"

    track = meta.get("track") or "?"
    kind = meta.get("kind") or "?"

    preamble = _PREAMBLE_TMPL.format(
        ticket=ticket, phase_id=phase_id, track=track, kind=kind
    )

    # Body: role prompt file (if any), read verbatim.
    body = ""
    if phase.prompt:
        prompt_path = framework_root() / phase.prompt
        if prompt_path.exists():
            body = "## Role prompt\n\n" + prompt_path.read_text(encoding="utf-8")
        else:
            body = (f"## Role prompt\n\n_MISSING: `{phase.prompt}` — "
                    "file referenced by phases.yml does not exist_\n")
    else:
        # No agent phase. Generate a lightweight checklist from inputs.
        if phase_id == "observe":
            body = _observe_checklist(ticket, meta)
        elif phase_id == "integrate":
            body = _integrate_checklist(ticket, meta)
        elif phase_id == "intake":
            body = ("## Manual step\n\nThis phase was created by "
                    "`klc intake`. Review raw.md and run "
                    f"`klc ack {ticket}` when you're ready to proceed.\n")
        else:
            body = f"## Manual step\n\n(no agent prompt for `{phase_id}`)\n"

    inputs_block = _format_inputs(ticket, phase)
    outputs_block = _format_outputs(phase)
    ack_instruction = _format_ack_instruction(ticket, phase)

    text = (
        preamble
        + body.rstrip() + "\n"
        + _INPUTS_TMPL.format(inputs_block=inputs_block)
        + _OUTPUTS_TMPL.format(
            outputs_block=outputs_block,
            ack_instruction=ack_instruction,
        )
    )
    card.write_text(text, encoding="utf-8")
    return card


def write_step_card(ticket: str, step: int, meta: dict,
                    inline: bool | None = None) -> Path:
    """Render `.klc/tickets/<ticket>/build/_prompt_step_N.md`.

    By default (compressed mode) the impl.md role prompt is referenced
    by path rather than embedded. Set inline=True (or env
    KLC_CARD_INLINE=1) to embed the full prompt for paste-only workflows.
    """
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        sys.stderr.write("artefacts: jinja2 not installed (pip install jinja2)\n")
        sys.exit(1)

    # Resolve inline mode: explicit arg wins over env var.
    if inline is None:
        inline = os.environ.get("KLC_CARD_INLINE", "").strip() == "1"

    tdir = klc_ticket_dir(ticket)
    build_dir = tdir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    card = build_dir / f"_prompt_step_{step}.md"

    fw = framework_root()
    env = Environment(loader=FileSystemLoader(str(fw / "core" / "templates")),
                      keep_trailing_newline=True)
    tmpl = env.get_template("impl-step.md.j2")

    # --- extract goals+ACs from spec.md ---
    goals_block = _extract_goals_acs(tdir / "spec.md")

    # --- extract current step from impl-plan.md (KLC-113: the ONE parser —
    # parse_impl_plan_steps + extract_step_fields, no second fork) ---
    plan_path = tdir / "impl-plan.md"
    plan_steps = (parse_impl_plan_steps(plan_path.read_text(encoding="utf-8"))
                  if plan_path.exists() else [])
    current_step = next((s for s in plan_steps if s["id"] == f"step-{step}"), None)
    fields = (extract_step_fields(current_step["body"])
              if current_step is not None else {})
    step_title = current_step["title"] if current_step is not None else f"step-{step}"

    # --- impl role prompt: reference (compressed) or embed (inline) ---
    impl_prompt_path = fw / "core" / "agents" / "impl.md"
    if inline:
        impl_prompt = (impl_prompt_path.read_text(encoding="utf-8")
                       if impl_prompt_path.exists() else
                       "_(impl.md not found)_")
        impl_prompt_ref = None
    else:
        impl_prompt = None
        impl_prompt_ref = (str(impl_prompt_path)
                           if impl_prompt_path.exists() else None)

    rendered = tmpl.render(
        ticket=ticket,
        track=meta.get("track") or "?",
        kind=meta.get("kind") or "?",
        step=step,
        goals_block=goals_block,
        step_title=step_title,
        step_goal=fields.get("goal", ""),
        step_affected=fields.get("affected", []),
        step_red=fields.get("red", ""),
        step_verify=fields.get("verify", ""),
        step_commit=fields.get("commit", ""),
        step_rollback=fields.get("rollback", ""),
        impl_prompt=impl_prompt,
        impl_prompt_ref=impl_prompt_ref,
    )
    card.write_text(rendered, encoding="utf-8")
    return card


def _extract_goals_acs(spec_path: Path) -> str:
    """Extract Goals and Acceptance Criteria sections from spec.md."""
    if not spec_path.exists():
        return f"_(spec.md not found at {spec_path})_"
    text = spec_path.read_text(encoding="utf-8")
    # Pull ## Goals and ## Acceptance Criteria sections
    sections = []
    for header in ("## Goals", "## Acceptance Criteria"):
        m = re.search(
            rf"^{re.escape(header)}\s*\n(.*?)(?=\n## |\Z)",
            text, re.MULTILINE | re.DOTALL
        )
        if m:
            sections.append(f"{header}\n\n{m.group(1).strip()}")
    return "\n\n".join(sections) if sections else "_(could not parse spec.md)_"


def _observe_checklist(ticket: str, meta: dict) -> str:
    """observe:work is a wait-and-watch. Build a checklist from the
    ticket's own spec/adr/design output rather than calling an agent."""
    lines = [
        "## Observation checklist",
        "",
        "No agent runs in this phase. The task is to monitor the "
        "merged change for regressions and close the loop with `klc ack`.",
        "",
        "Suggested watchlist (customise per ticket):",
        "",
        "- [ ] Error-rate dashboard for affected service(s)",
        "- [ ] p95 / p99 latency for the touched endpoints",
        "- [ ] Relevant SLO budget burn rate",
        "- [ ] Feature flag rollout percentage (if applicable)",
        "- [ ] User-report channels (support, feedback) for regressions",
        "",
        f"When the observation window closes, run `klc ack {ticket} "
        f"--pick 1` (clean), `--pick 2` (regression, auto-reopens "
        f"build), or `--pick 3` (rollback).",
    ]
    return "\n".join(lines)


def _integrate_checklist(ticket: str, meta: dict) -> str:
    lines = [
        "## Integration checklist",
        "",
        "This phase has two ticks. During `:work`:",
        "",
        "### Tick 1 — pre-merge",
        "- [ ] Snapshot current artefact hashes (consistency guard).",
        "- [ ] Open the PR / merge request.",
        "- [ ] Address any CI / reviewer blockers.",
        "",
        "### Tick 2 — post-merge",
        "- [ ] Record merge commit SHA in meta.json.",
        "- [ ] Verify CI is green on main.",
        "- [ ] Close the Jira / tracker ticket.",
        "",
        f"When both ticks are done, run `klc ack {ticket}`.",
    ]
    return "\n".join(lines)
