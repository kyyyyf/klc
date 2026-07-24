#!/usr/bin/env python3
"""autorunner.py — the autonomous runner behind `klc run <KEY>` (KLC-046).

A thin, bounded driver over the EXISTING skills. It reuses — never reinvents —
the pieces the manual lifecycle already trusts:

  - `build_orchestrator.run_build` / `runner.run_agent`  → dispatch a phase agent
  - `core/phases/ack.py::run([KEY, "--auto"])`           → the IDENTICAL transition
    a human `klc ack --auto` takes (gate-policy applied inside)
  - `lifecycle` / `phases`                               → read/advance state
  - `budget`                                             → budget-ceiling guardrail

The loop drives a ticket forward on its own, bounded by guardrails so it can
NEVER silently take an irreversible or risky action:

  * outward-facing/irreversible phases (integrate/merge) ALWAYS pause;
  * a budget ceiling pauses;
  * a cap on consecutive auto-transitions pauses (runaway backstop);
  * a decision gate always pauses (inside `ack --auto`);
  * a dirty conditional gate pauses (inside `ack --auto`).

SCOPE BOUNDARY (AC-7): SINGLE-USER / feature-OFF only. When `state_feature`
is ON (a multi-user `klc-state` worktree with an upstream), the runner refuses.
Multi-user autonomous running would need CAS-push per ack, holder management,
and rc-1 sync-error disambiguation — none of which this driver implements.
Feature-off, `ack --auto` returns rc 0 (advanced) or rc 2 (gate pause) and never
the feature-on rc-1 sync errors, so the loop reads: 0 = advanced, 2 = gate pause,
any other non-zero = an error pause with its own message.

The `:work → :ack-needed` transition happens INSIDE `klc ack` (via
`phase_completion.can_complete`), NOT in `lifecycle`. So at a `:work` state the
loop dispatches then calls `ack --auto`; a single `--auto` from `:work`
auto-detects completion and walks `:work → :ack-needed → (gate)` in one call.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import io
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- import path bootstrap ---------------------------------------------------
_SKILLS = Path(__file__).resolve().parent
_PHASES = _SKILLS.parent / "phases"
for _p in (_SKILLS, _PHASES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lifecycle as _lc          # noqa: E402
import phases as _ph             # noqa: E402
import epic_deps as _edeps       # noqa: E402  KLC-077 BlockedError → clean pause
import budget as _budget         # noqa: E402
import state_feature             # noqa: E402
import build_orchestrator        # noqa: E402
import runner                    # noqa: E402
import artefacts as _artefacts   # noqa: E402  renders the per-ticket prompt card
import ack as _ack_cmd           # noqa: E402  core/phases/ack.py — reuse, do not reimplement
from _paths import klc_ticket_dir, klc_ticket_meta_file, framework_root  # noqa: E402


# ---------------------------------------------------------------------------
# guardrail configuration
# ---------------------------------------------------------------------------

# Outward-facing / irreversible phases that must ALWAYS pause for a human.
# Driven by phase-id, NOT a pick goto/label heuristic: `integrate` is the only
# phase that merges/pushes in the state machine, and no phases.yml pick label
# contains "push". Add ANY future merge/push/outward phase here.
_OUTWARD_PHASES = {"integrate"}

# Consecutive-auto-transition cap. This is a runaway backstop, NOT a budget
# counter: it is deliberately kept OUT of `.klc/config/budgets.yml` /
# `budget._load_limits()` (which feed `gate_policy.budget_overrun`). Resolution
# order: KLC_AUTORUN_CAP env → framework `config/budgets.yml`
# top-level `consecutive_auto_transitions:` → this default.
_DEFAULT_CAP = 20


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    transitions: list[str] = field(default_factory=list)  # phase-ids auto-acked, in order
    paused_at: str | None = None                          # phase-id where the loop stopped
    reason: str | None = None                             # why it stopped (None = clean terminal)
    terminal: str | None = None                           # terminal state reached: "archived"/"cancelled" (KLC-076)


# ---------------------------------------------------------------------------
# cap loader (separate from budget counters — audit fix #3)
# ---------------------------------------------------------------------------

def _cap() -> int:
    env = os.environ.get("KLC_AUTORUN_CAP")
    if env and env.strip().isdigit():
        return int(env.strip())
    cfg = framework_root() / "config" / "budgets.yml"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*consecutive_auto_transitions\s*:\s*(\d+)", line)
            if m:
                return int(m.group(1))
    except OSError:
        pass
    return _DEFAULT_CAP


# ---------------------------------------------------------------------------
# guardrail predicate (AC-4)
# ---------------------------------------------------------------------------

def _any_budget_at_limit(ticket: str) -> bool:
    """True when any meta.budgets counter is at/over its limit (same logic as
    budget.cmd_check). Reuses budget._load_limits()."""
    limits = _budget._load_limits()
    cur = (_lc.read_meta(ticket).get("budgets") or {})
    return any(int(cur.get(c, 0)) >= lim for c, lim in limits.items())


def guardrail(ticket: str, phase_id: str, n_auto: int, cap: int) -> str | None:
    """Return a pause reason if the loop must stop BEFORE acting on `phase_id`,
    else None. Fail-closed: pause when uncertain."""
    if phase_id in _OUTWARD_PHASES:
        return (f"outward-facing/irreversible guardrail: {phase_id} "
                f"(integrate/merge) — human required")
    if _any_budget_at_limit(ticket):
        return f"budget-ceiling guardrail: a budget counter reached its limit at {phase_id}"
    if n_auto >= cap:
        return f"consecutive-auto-cap guardrail: cap {cap} reached"
    return None


# ---------------------------------------------------------------------------
# dispatch (AC-1)
# ---------------------------------------------------------------------------

def _card_path(ticket: str, phase_id: str) -> Path:
    """The RENDERED per-ticket prompt card — the file that carries the concrete
    key, resolved input paths, and output/ack instructions. This is what a phase
    agent must be dispatched with, NOT the generic `core/agents/<phase>.md` role
    prompt (full of <KEY> placeholders). Rendered fresh so inputs are current;
    `write_prompt_card` is idempotent (same file the manual `klc ack`/`klc next`
    path writes on entering a `:work` phase)."""
    meta = _lc.read_meta(ticket)
    return _artefacts.write_prompt_card(ticket, phase_id, meta)


def _out_path(ticket: str, phase_id: str) -> Path:
    """The response sink for `run_agent` (where the raw agent response lands).
    The DECLARED artifacts are written by the agent itself per the card; whether
    the RIGHT set was produced is decided by `ack --auto`'s can_complete gate
    (which is track-aware), NOT by the runner — see the note in the run loop."""
    return klc_ticket_dir(ticket) / phase_id / "_response.md"


# Sentinel rc for a phase that has no agent prompt (a checklist phase like
# observe/integrate): not auto-dispatchable → the loop pauses fail-closed.
_DISPATCH_NO_PROMPT = 90


def _dispatch(ticket: str, phase_id: str, dispatch) -> int:
    """Dispatch the current :work phase agent with the resolved model.

    build  → KLC-042 build_orchestrator (per-step subagents; resolves model)
    others → runner.run_agent with the RENDERED per-ticket card (not the generic
             role prompt), passing BOTH track= (model resolution) and ticket= so
             the interactive-park guard (C-005) fires — an interactive phase
             (e.g. a clarify-required intake) parks with PARK_RC instead of being
             guessed at headlessly, which the loop surfaces as a non-zero rc →
             pause. ticket= also records token usage.
    Returns the dispatch rc; a non-zero rc is surfaced to the loop.
    """
    if phase_id == "build":
        return build_orchestrator.run_build(ticket, dispatch=dispatch)
    phase = _ph.load_phases().by_id(phase_id)
    if not phase.prompt:
        # No agent prompt (checklist phase). integrate is already stopped by the
        # guardrail; any other empty-prompt :work (e.g. observe on a resumed run)
        # is not auto-dispatchable — fail-closed so the loop pauses for a human.
        return _DISPATCH_NO_PROMPT
    d = dispatch or runner.run_agent
    track = _lc.read_meta(ticket).get("track")
    return d(phase_id, _card_path(ticket, phase_id), _out_path(ticket, phase_id),
             track=track, ticket=ticket)


# ---------------------------------------------------------------------------
# ack reuse + pause classification
# ---------------------------------------------------------------------------

def _ack_auto(ticket: str) -> tuple[int, str]:
    """The IDENTICAL transition a human `klc ack --auto` takes. Captures ack's
    stderr so a pause reason can name the real cause (incomplete artifacts /
    scope expansion / holder conflict) instead of a bare rc."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        rc = _ack_cmd.run([ticket, "--auto"])
    return rc, buf.getvalue()


def _forced_pick(phase):
    """The unambiguous forward pick (goto=='next'), mirroring KLC-045's
    _resolve_auto_pick. Used ONLY to classify a pause reason, never to ack."""
    fwd = [p for p in phase.picks if p.goto == "next"]
    if fwd:
        return fwd[0]
    return phase.picks[0] if len(phase.picks) == 1 else None


def _gate_reason(ticket: str, phase_id: str) -> str:
    """Classify why `ack --auto` paused (rc 2) at phase_id:ack-needed."""
    try:
        pick = _forced_pick(_ph.load_phases().by_id(phase_id))
        if pick is not None and pick.gate == "decision":
            return f"decision gate at {phase_id}:ack-needed — human decision required"
    except Exception:
        pass
    return f"gate-policy paused at {phase_id}:ack-needed — signals not clean"


# ---------------------------------------------------------------------------
# run log + notifications (AC-6)
# ---------------------------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(ticket: str, entry: str) -> None:
    path = klc_ticket_dir(ticket) / "run-log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"- {_now()} — {entry}\n")


def _notify(ticket: str, reason: str) -> None:
    """Emit a pause notification. stderr is the always-on channel; the run log
    keeps the durable record a human reads when resuming."""
    sys.stderr.write(f"klc run {ticket}: PAUSED — {reason}\n")


def _pause(ticket: str, trace: list[str], phase_id: str, reason: str) -> RunResult:
    _log(ticket, f"PAUSED at {phase_id}: {reason}")
    _notify(ticket, reason)
    return RunResult(list(trace), phase_id, reason)


# ---------------------------------------------------------------------------
# the bounded run loop (AC-1, AC-2, AC-3, AC-5, AC-7)
# ---------------------------------------------------------------------------

def run(ticket: str, *, dispatch=None, cap: int | None = None) -> RunResult:
    # P2: validate the ticket exists BEFORE any _log/state mutation, so
    # `klc run <BADKEY>` gives a friendly error and never creates a bogus dir.
    if not klc_ticket_meta_file(ticket).exists():
        reason = (f"unknown ticket {ticket!r}; run `klc intake {ticket}` "
                  f"or `klc board` to list live tickets")
        sys.stderr.write(f"klc run: {reason}\n")
        return RunResult([], None, reason)

    # AC-7 scope boundary: refuse a multi-user (feature-ON) autonomous run.
    if state_feature.enabled():
        reason = ("refused: multi-user state feature is ON — the autonomous "
                  "runner is single-user (feature-off) only")
        _log(ticket, reason)   # ticket exists → safe to log
        sys.stderr.write(f"klc run {ticket}: {reason}\n")
        return RunResult([], None, reason)

    cap = cap if cap is not None else _cap()
    n_auto = 0
    trace: list[str] = []
    last_pid = "?"
    _log(ticket, f"run start (cap={cap})")

    try:
        while True:
            pid, state = _ph.parse_state(_lc.current_state(ticket))
            last_pid = pid
            if _ph.is_terminal(state):
                # archived (done) and cancelled (terminated early) are both CLEAN
                # terminal stops — the runner has nothing left to drive (KLC-076).
                # reason stays None (a set reason with no paused_at means a
                # refusal → rc 1); the terminal name is carried in `terminal` so
                # run.py can report "DONE (cancelled)" distinctly and still exit 0.
                _log(ticket, f"done: {state}")
                return RunResult(list(trace), None, None, terminal=state)

            # Guardrails BEFORE any dispatch or auto-ack (fail-closed).
            stop = guardrail(ticket, pid, n_auto, cap)
            if stop:
                return _pause(ticket, trace, pid, stop)

            if state in (_ph.STATE_WORK, _ph.STATE_ACK_NEEDED):
                if state == _ph.STATE_WORK:
                    rc = _dispatch(ticket, pid, dispatch)
                    if rc != 0:
                        return _pause(ticket, trace, pid,
                                      f"dispatch failed (rc={rc}) at {pid}:work")
                    _log(ticket, f"dispatched {pid}:work (rc=0)")
                # ack --auto: walks work→ack-needed→(gate) or acks an ack-needed.
                # Whether the dispatch produced enough/correct artifacts is decided
                # here by ack's can_complete gate, which is TRACK-AWARE (e.g. XS
                # discovery-lite needs only spec.md, S needs spec+options-lite+
                # impl-plan; phases.yml `outputs` is a superset, not the required
                # set). The runner does NOT duplicate that per-track logic — an
                # insufficient dispatch returns rc 1 here and pauses fail-closed
                # with the gate's own causal reason surfaced below.
                rc, err = _ack_auto(ticket)
                if rc == 0:
                    n_auto += 1
                    trace.append(pid)
                    _log(ticket, f"auto-acked {pid} → {_lc.current_state(ticket)} "
                                 f"(n_auto={n_auto})")
                    continue
                if rc == 2:
                    return _pause(ticket, trace, pid, _gate_reason(ticket, pid))
                # Surface the FULL causal diagnostic (not just the last line, which
                # is usually the generic abort/remediation hint) so a resuming
                # human sees the actual cause (missing artifact / scope expansion).
                lines = [ln.strip() for ln in err.strip().splitlines() if ln.strip()]
                detail = f": {' | '.join(lines)}" if lines else ""
                return _pause(ticket, trace, pid,
                              f"ack --auto error (rc={rc}) at {pid}{detail}")

            # A lingering :ack state (rare in the auto path) — advance it.
            _lc.advance_to_next(ticket)
            _log(ticket, f"advanced {pid}:ack → {_lc.current_state(ticket)}")
    except _edeps.BlockedError as be:
        # KLC-077: the epic dependency guard fired on a :work entry (e.g. the
        # lingering-:ack advance above, or any advance_to_next path). This is a
        # CLEAN PAUSE like a decision gate — stop without advancing and name the
        # blocker, NOT a fail-closed crash.
        return _pause(ticket, trace, last_pid, be.edge.message())
    except Exception as exc:  # fail-closed: never crash — pause and log
        return _pause(ticket, trace, last_pid,
                      f"unexpected error — paused fail-closed: {exc!r}")


if __name__ == "__main__":  # pragma: no cover
    import json as _json
    res = run(sys.argv[1])
    print(_json.dumps({"transitions": res.transitions,
                       "paused_at": res.paused_at, "reason": res.reason}))
    # Mirror run.py's three-way rc: pause→2, refusal→1, done→0.
    if res.paused_at is not None:
        sys.exit(2)
    sys.exit(1 if res.reason is not None else 0)
