#!/usr/bin/env python3
"""artefacts.py — prompt-card generation and per-ticket lock.

The phase scripts were deleted when klc became data-driven. The two
pieces they still owned — producing a copypaste-ready prompt for the
agent, and taking a lock so two terminals can't race on `next`/`ack` —
live here now.

Responsibilities:

  write_prompt_card(ticket, phase_id)
      Render the prompt for a phase into
      `.klc/tickets/<ticket>/<phase>/_prompt.md`. Content:
        - a short preamble (ticket key, track, state, phase purpose)
        - the agent prompt body from phases.yml:work.prompt
        - pointers to relevant inputs (resolved from phase.inputs).
      For phases without a prompt (intake, observe), writes a
      checklist or pointer card instead. Returns the absolute path.

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
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import framework_root, klc_ticket_dir  # noqa: E402
import phases as _ph  # noqa: E402


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

Ticket: **{ticket}** · track: **{track}** · kind: **{kind}**

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


def write_prompt_card(ticket: str, phase_id: str, meta: dict) -> Path:
    """Render `.klc/tickets/<ticket>/<phase>/_prompt.md`. Returns the path."""
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
