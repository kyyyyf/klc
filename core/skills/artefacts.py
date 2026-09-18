#!/usr/bin/env python3
"""artefacts.py — prompt-card generation and per-ticket lock.

The phase scripts were deleted when klc became data-driven. The two
pieces they still owned — producing a copypaste-ready prompt for the
agent, and taking a lock so two terminals can't race on `next`/`ack` —
live here now.

Responsibilities:

  write_prompt_card(ticket, phase_id, meta, step=None)
      Render the prompt for a phase into
      `<card root>/<ticket>/<phase>/_prompt.md` (KLC-118; card root is
      `core.shared.paths.klc_card_root()`, `.klc/scratch/` by default,
      overridable with `KLC_CARD_ROOT`). Content:
        - a short preamble (ticket key, track, state, phase purpose)
        - the agent prompt body from phases.yml:work.prompt
        - pointers to relevant inputs (resolved from phase.inputs).
      For phases without a prompt (intake, observe), writes a
      checklist or pointer card instead. Returns the absolute path.
      When phase_id == "build" and step is given, renders the minimal
      impl-step.md.j2 card instead (only current step context).

  write_step_card(ticket, step, meta)
      Render `<card root>/<ticket>/build/_prompt_step_N.md` for a
      specific TDD step. Uses impl-step.md.j2. Returns the path.

  card_path(ticket, phase_id, step=None)
      The one place any reader learns where a card lives. Canonical
      (card root) first; a card left in the ticket directory by a
      degraded render or a pre-migration layout is the fallback.

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
from dataclasses import dataclass
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import (  # noqa: E402
    framework_root, klc_ticket_dir, klc_card_root, klc_card_path, CARD_ROOT_ENV,
    klc_tickets_dir,
)
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


# --- card render modes (KLC-118) -----------------------------------------------
#
# `dispatch`: for a Task-tool dispatch, whose subagent definition already
#   carries the full role prompt (klc-plugin/agents/<stem>.md) — the card
#   must NOT send it a second time. The `## Role prompt` section becomes a
#   pointer naming the file by absolute path.
# `paste`:    today's fully-inlined card — byte-identical, for a human
#   pasting into a chat and for the headless providers (C-003), which get one
#   flat prompt string and cannot follow a filesystem reference.

CARD_MODE_DISPATCH = "dispatch"
CARD_MODE_PASTE = "paste"

_PREAMBLE_DISPATCH_TMPL = """\
# Agent prompt — {ticket} · {phase_id}:work

You are working in phase **{phase_id}**. Your subagent definition already
carries this phase's role prompt; this card adds the ticket context only.
When you claim the work is done, the human runs `klc ack {ticket}` (with
`--pick N` if required) to confirm.

"""


def _resolve_mode(mode: str) -> str:
    """`KLC_CARD_INLINE=1` forces `paste` (generalises the flag
    `write_step_card` has had since KLC-072); any value other than the
    `dispatch` constant degrades to `paste` — the failure direction of a
    bigger prompt is always safer than a silently missing role prompt."""
    if os.environ.get("KLC_CARD_INLINE", "").strip() == "1":
        return CARD_MODE_PASTE
    return CARD_MODE_DISPATCH if mode == CARD_MODE_DISPATCH else CARD_MODE_PASTE


def _role_prompt_block(phase: _ph.Phase, mode: str) -> str:
    """The `## Role prompt` section for an agent phase (one with
    `phase.prompt`). Dispatch mode NEVER embeds a body — not even when the
    file referenced by phases.yml is missing (fail-closed: a caller must not
    be able to coax an embedded body out of dispatch mode)."""
    path = framework_root() / phase.prompt
    if mode == CARD_MODE_DISPATCH:
        return ("## Role prompt\n\n"
                "Already loaded: your subagent definition carries the full "
                "role prompt for this phase. Source of truth on disk (open "
                f"only if you need to re-read it):\n`{path.resolve()}`\n")
    if path.exists():
        return "## Role prompt\n\n" + path.read_text(encoding="utf-8")
    return (f"## Role prompt\n\n_MISSING: `{phase.prompt}` — "
            "file referenced by phases.yml does not exist_\n")


def _card_dir(ticket: str, phase_id: str) -> tuple[Path, bool]:
    """(directory, degraded). Never raises: a card that cannot be written to
    the card root falls back to the ticket dir rather than failing the phase
    transition (KLC-118 AC-12)."""
    target = klc_card_root() / ticket / phase_id
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return target, False
    except OSError as exc:
        sys.stderr.write(
            f"artefacts: card root {target} unusable ({exc}); "
            f"falling back to the ticket directory\n"
        )
        fallback = klc_ticket_dir(ticket) / phase_id
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback, True


def card_path(ticket: str, phase_id: str, step: int | None = None) -> Path:
    """The one place any reader learns where a card lives (KLC-118 AC-8).
    Canonical location (the card root) first; a card left in the ticket
    directory by a degraded render (AC-12) or by a pre-migration layout is
    honoured only when the canonical one is absent."""
    canonical = klc_card_path(ticket, phase_id, step)
    if canonical.exists():
        return canonical
    name = f"_prompt_step_{step}.md" if step is not None else "_prompt.md"
    legacy = klc_ticket_dir(ticket) / phase_id / name
    return legacy if legacy.exists() else canonical


def write_prompt_card(ticket: str, phase_id: str, meta: dict,
                      step: int | None = None,
                      mode: str = CARD_MODE_PASTE) -> Path:
    """Render the phase's prompt card at the card root
    (`<card root>/<ticket>/<phase>/_prompt.md`, KLC-118). Returns the path.

    `mode`: `CARD_MODE_DISPATCH` omits the role-prompt body (the subagent
    definition already carries it) and names the file instead;
    `CARD_MODE_PASTE` (default) is byte-identical to the pre-KLC-118 card.
    `KLC_CARD_INLINE=1` forces paste; an unrecognised mode degrades to paste.

    When phase_id == "build" and step is given, delegates to
    write_step_card() which uses the minimal impl-step template.
    """
    if phase_id == "build" and step is not None:
        return write_step_card(ticket, step, meta)

    ph = _ph.load_phases()
    phase = ph.by_id(phase_id)
    phase_dir, _degraded = _card_dir(ticket, phase_id)
    card = phase_dir / "_prompt.md"

    track = meta.get("track") or "?"
    kind = meta.get("kind") or "?"

    # A checklist phase (no phase.prompt) has nothing to strip — it renders
    # identically regardless of mode (design/options.md Shared mechanics).
    effective_mode = _resolve_mode(mode) if phase.prompt else CARD_MODE_PASTE

    preamble_tmpl = (_PREAMBLE_DISPATCH_TMPL
                     if effective_mode == CARD_MODE_DISPATCH else _PREAMBLE_TMPL)
    preamble = preamble_tmpl.format(
        ticket=ticket, phase_id=phase_id, track=track, kind=kind
    )

    body = ""
    if phase.prompt:
        body = _role_prompt_block(phase, effective_mode)
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
    build_dir, _degraded = _card_dir(ticket, "build")
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


@dataclass
class CardRender:
    """The measured record of a card render (KLC-118 AC-5/AC-6)."""
    path:       Path
    card_bytes: int
    est_tokens: int
    degraded:   bool


def render_card(ticket: str, phase_id: str, meta: dict,
                step: int | None = None, mode: str = CARD_MODE_PASTE) -> CardRender:
    """The measuring entry point: render the card (via the existing
    path-returning writers, which keep their nine call sites unchanged) and
    record its byte size + an estimated token count into
    `meta.json:metrics.tokens.<phase_id>` (`source="estimated"`, never
    downgrading a `provider` record — see `budget_guard.write_token_metrics`).
    `klc next` is the one caller that needs the measured numbers; every other
    call site keeps using `write_prompt_card`/`write_step_card` directly."""
    if phase_id == "build" and step is not None:
        path = write_step_card(ticket, step, meta)
    else:
        path = write_prompt_card(ticket, phase_id, meta, step=step, mode=mode)
    text = path.read_text(encoding="utf-8")
    card_bytes = len(text.encode("utf-8"))
    degraded = not str(path).startswith(str(klc_card_root()))
    est_tokens = _record_card_metrics(ticket, phase_id, text, card_bytes)
    if not degraded:
        # KLC-118 AC-10 / impl-plan-review F-2 / DECISION D-2: the automatic
        # sweep is scoped to THIS ticket AND THIS phase only — never the
        # whole ticket subtree — so it can never delete a SIBLING phase's
        # still-live, legitimately-degraded card (AC-12). A degraded render
        # skips the sweep outright: it just wrote the very file a
        # ticket-wide sweep would otherwise be tempted to remove.
        sweep_legacy_cards(ticket=ticket, phase_id=phase_id)
    return CardRender(path=path, card_bytes=card_bytes, est_tokens=est_tokens,
                      degraded=degraded)


_LEGACY_CARD_GLOBS = ("_prompt.md", "_prompt_step_*.md")


def sweep_legacy_cards(ticket: str | None = None,
                       phase_id: str | None = None) -> list[Path]:
    """Delete prompt cards left under the ticket tree by the pre-KLC-118
    layout. Pure filesystem deletion: the files were never tracked
    (FACT F-006), so the state branch is untouched and no commit is produced.

    Scope (KLC-118 D-2):
      - `ticket=None` (the bare/global form): every live ticket's whole
        subtree — reserved for the explicit `sweep-cards` CLI subcommand's
        one-shot operator use, never invoked automatically.
      - `ticket=<KEY>, phase_id=None`: one ticket's whole subtree — the
        `sweep-cards <KEY>` CLI form.
      - `ticket=<KEY>, phase_id=<phase>`: ONE phase's directory only — what
        `render_card` invokes automatically on every canonical render
        (F-2: a ticket-wide automatic sweep could delete a sibling phase's
        still-live, legitimately-degraded card).
    """
    if ticket and phase_id:
        roots = [klc_ticket_dir(ticket) / phase_id]
    elif ticket:
        roots = [klc_ticket_dir(ticket)]
    else:
        tickets_dir = klc_tickets_dir()
        roots = ([p for p in sorted(tickets_dir.iterdir())
                 if p.is_dir() and p.name != "archive"]
                if tickets_dir.exists() else [])
    removed: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in _LEGACY_CARD_GLOBS:
            for stale in root.rglob(pattern):
                try:
                    stale.unlink()
                    removed.append(stale)
                except OSError:
                    pass
    return removed


def _record_card_metrics(ticket: str, phase_id: str, text: str,
                         card_bytes: int) -> int:
    """Non-fatal telemetry write (mirrors runner.py's own try/except around
    write_token_metrics) — a metrics failure must never fail a card render."""
    try:
        import budget_guard
    except ImportError:
        return max(1, card_bytes // 4)
    est_tokens = budget_guard.estimate_tokens(text)
    try:
        budget_guard.write_token_metrics(
            ticket, phase_id, est_tokens, 0, 0,
            source="estimated", card_bytes=card_bytes)
    except Exception:
        pass
    return est_tokens


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


def _main(argv: list[str]) -> int:
    """`python3 core/skills/artefacts.py sweep-cards [KEY]` — the one-shot
    operator entry point for the migration sweep (KLC-118 AC-10). With no KEY,
    sweeps every live ticket; with KEY, that ticket's whole subtree."""
    if not argv or argv[0] != "sweep-cards":
        sys.stderr.write("usage: artefacts.py sweep-cards [KEY]\n")
        return 2
    ticket = argv[1] if len(argv) > 1 else None
    removed = sweep_legacy_cards(ticket=ticket)
    for path in removed:
        print(f"removed {path}")
    print(f"swept {len(removed)} stale card(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
