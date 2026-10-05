"""next_move.py — the one read that answers "what does `klc go` do next?".

`compute(ticket)` looks at the ticket's state and returns a `Move`. `klc go`
acts on it, `klc status` prints its one-line `render()`, and the later
`go --until` loop reuses it. Keeping the decision in one function is what lets
`go --dry-run` and the last line of `status` always agree.

The read never writes: it uses `lifecycle.read_meta_ro`, probes completeness
with `can_complete(persist=False)` and only reads gate signals.

Actions:
  done   — terminal ticket, nothing to do
  next   — state `:ack`, advance into the next phase's `:work`
  ack    — gate lets `go` ack on its own (auto-pick the forward pick)
  clarify — intake with `meta.clarify_required` true: the main agent runs the
           clarify pass first, then `go --pick 1` confirms the route
  pick   — a decision gate or a dirty conditional gate: a human gives `--pick N`
  agent  — `:work` with missing outputs: the agent behind the card must run

One unusual point: at `:work` the advisory signal is not judged, because the
advisory record is only written when `ack` completes the phase. The remaining
signals are judged, and `ack --auto` judges the advisory after it persists it.
"""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import artefacts as _artefacts  # noqa: E402
import gate_policy as _gp  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phase_completion as _pc  # noqa: E402
import phases as _ph  # noqa: E402
import rules as _rules  # noqa: E402


@dataclass
class Move:
    ticket: str
    state: str                      # ack | ack-needed | work | archived | cancelled
    action: str                     # done | next | ack | pick | clarify | agent
    phase: str = ""
    reason: str = ""                # why go cannot ack on its own (gate reasons, missing outputs)
    card: str = ""                  # prompt card path, set at :work
    picks: list = field(default_factory=list)   # [(id, label)] of the phase
    forward_pick: int | None = None
    enters: str = ""                # phase whose :work the rule table enters after this ack ("" = archive)
    blocked_on: str | None = None   # the decision fact (spec_approved / design_approved) a pick approves

    def as_dict(self) -> dict:
        return asdict(self)


def forward_pick(phase: "_ph.Phase"):
    """The pick `ack --auto` takes: the first `goto: next`, else the only pick."""
    fwd = [p for p in phase.picks if p.goto == "next"]
    if fwd:
        return fwd[0]
    return phase.picks[0] if len(phase.picks) == 1 else None


def _gate_verdict(ticket: str, phase: "_ph.Phase", *, judge_advisory: bool) -> tuple[bool, str]:
    pick = forward_pick(phase)
    if pick is None:
        return False, "no unambiguous forward pick"
    signals = _gp.collect_signals(ticket, phase.id)
    if not judge_advisory:
        signals = {**signals, "advisory": {"records": [], "threshold": "medium"}}
    decision = _gp.evaluate(pick.gate, signals)
    reasons = list(decision.reasons)
    merge = _gp.merge_gate(ticket, phase.id)          # F-003: integrate must really be merged
    return decision.proceed and not merge, "; ".join(reasons + merge)


def _card(ticket: str, pid: str, meta: dict) -> str:
    if pid == "build":
        return str(_artefacts.card_path(ticket, "build", meta.get("impl_step") or 1))
    return str(_artefacts.card_path(ticket, pid))


def compute(ticket: str) -> Move:
    meta = _lc.read_meta_ro(ticket)
    value = meta.get("phase") or "intake:ack-needed"
    if value in (_ph.STATE_ARCHIVED, _ph.STATE_CANCELLED):
        return Move(ticket, value, "done", phase=value)

    pid, state = _ph.parse_state(value)
    phase = _ph.load_phases().by_id(pid)
    picks = [(p.id, p.label) for p in phase.picks]
    move = Move(ticket, state, "next", phase=pid, picks=picks)
    pick = forward_pick(phase)
    move.forward_pick = pick.id if pick else None
    # KLC-179: where the ticket goes next, and which human decision it waits for, come
    # from the facts rule table, not from a walk over phases.yml.
    facts = _rules.derive_facts(meta)
    if state == _ph.STATE_ACK_NEEDED:        # a decision fact is written only by the pick itself
        facts = _rules.if_approved(facts, pid, _rules.lane_of(meta))
    nxt = _rules.next_move(facts, _rules.lane_of(meta), risk_tags=meta.get("risk_tags"))
    move.enters = nxt.phase if nxt.action not in ("archive", "done") and nxt.phase else ""
    fact = _rules.PHASE_FACT.get(pid)
    move.blocked_on = fact if fact in _rules.DECISION_FACTS[_rules.lane_of(meta)] \
        and not _rules.holds(_rules.derive_facts(meta), fact) else None

    if state == _ph.STATE_ACK:
        return move

    if pid == "intake" and meta.get("clarify_required"):
        move.action = "clarify"
        move.reason = "low route confidence: the clarify pass has not run"
        return move

    if state == _ph.STATE_WORK:
        move.card = _card(ticket, pid, meta)
        ok, msg = _pc.can_complete(ticket, pid, persist=False)
        if not ok:
            move.action, move.reason = "agent", " ".join((msg or "outputs missing").split())
            return move

    proceed, reasons = _gate_verdict(ticket, phase, judge_advisory=state != _ph.STATE_WORK)
    move.action = "ack" if proceed else "pick"
    move.reason = "" if proceed else reasons
    return move


def render(move: Move) -> str:
    """The single next-action line, shared by `klc go --dry-run` and `klc status`."""
    k = move.ticket
    if move.action == "done":
        return ""
    if move.action == "next":
        return f"→ run `klc go {k}` to advance"
    if move.action == "agent":
        return (f"→ {move.phase}:work needs the agent. Prompt: `cat {move.card}` "
                f"— when it is done run `klc go {k}` ({move.reason})")
    if move.action == "clarify":
        return (f"→ clarify needed — run the clarify pass, then "
                f"klc go {k}")
    if move.action == "ack":
        return f"→ run `klc go {k}` to ack {move.phase} and move on"
    opts = ", ".join(f"{i}={label}" for i, label in move.picks)
    why = f"; {move.reason}" if move.reason else ""
    return f"→ run `klc go {k} --pick N` (options: {opts}{why})"
