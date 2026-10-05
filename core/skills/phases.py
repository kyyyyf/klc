#!/usr/bin/env python3
"""phases.py — the prompt table (config/phases.yml) and the state-string helpers.

Since KLC-179 this module no longer walks a transition matrix. The next phase is
decided by the facts rule table in core/skills/rules.py; phases.yml only holds
each phase's prompt, inputs, outputs and pick labels. Callers ask:

    ph = load_phases()
    ph.by_id("design").prompt
    ph.track_phases("M")          # ids in lifecycle order, taken from the rule table

States per phase: `<id>:work`, `<id>:ack-needed`, `<id>:ack`. Plus two
terminal pseudo-states that no phase owns: `archived` (the ticket finished
its lifecycle — "done") and `cancelled` (the ticket was terminated early and
will never be done — NOT counted as completed work; see KLC-076).

YAML parser is a small subset tailored to the shape of phases.yml:
  - top-level mapping;
  - lists of mappings;
  - string scalars (quoted or bare), bool, null, integer;
  - nested lists inside a mapping (e.g. picks: [approve, needs-rework]).

PyYAML is a hard dep of nothing else in the framework; we keep it out.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
if str(_file_dir) not in sys.path:
    sys.path.insert(0, str(_file_dir))
from core.shared.paths import framework_root  # noqa: E402
from core.shared.yaml import parse as _yaml_parse  # noqa: E402
import rules as _rules  # noqa: E402  (KLC-179: the order and the lanes live in the rule table)


STATE_WORK        = "work"
STATE_ACK_NEEDED  = "ack-needed"
STATE_ACK         = "ack"
STATE_ARCHIVED    = "archived"
STATE_CANCELLED   = "cancelled"    # KLC-076: terminated-early terminal (not "done")
VALID_STATES = {STATE_WORK, STATE_ACK_NEEDED, STATE_ACK}

# Terminal pseudo-states no phase owns. `archived` = finished/done;
# `cancelled` = terminated early (excluded from completion metrics). Consumers
# that must refuse to advance, or render/handle a finished ticket, gate on
# `is_terminal(...)` so a future third terminal is added in exactly one place.
TERMINAL_STATES = {STATE_ARCHIVED, STATE_CANCELLED}

TRACK_ORDER = ("XS", "S", "M", "L")


# --- data classes -------------------------------------------------------------

_DECISION_FACTS = ("spec_approved", "design_approved", "manual_passed")   # the human decision points


@dataclass
class Pick:
    """A `--pick N` choice. `forward` picks approve (the ticket moves to the next
    missing fact); the others rework, change route or loop a phase (rules.py decides
    where each leads). The gate is derived: only the approvals of the spec, the
    design and (when it runs) the manual check are `decision`; every other approval is `conditional`; a pick that is
    not an approval is always a `decision`."""
    id:      int
    label:   str
    forward: bool = True
    gate:    str = "conditional"

    @property
    def goto(self) -> str:
        """`next` for an approving pick, `rework` for any other (a marker, not a target)."""
        return "next" if self.forward else "rework"


@dataclass
class Phase:
    id:            str
    prompt:        str
    pick_required: bool
    picks:         list[Pick]
    inputs:        list[str]
    outputs:       list[str]

    def pick_by_id(self, pick_id: int) -> Pick | None:
        for p in self.picks:
            if p.id == pick_id:
                return p
        return None

    @property
    def tracks(self) -> list[str]:
        """Tracks whose lane can visit this phase (derived from the rule table)."""
        return [t for t in TRACK_ORDER if self.id in _rules.lane_phase_ids(t)]

    def should_run(self, meta: dict) -> bool:
        """False when the rule table would never enter this phase for this ticket."""
        return _rules.phase_applies(self.id, meta)


@dataclass
class Phases:
    """The loaded prompt table. Iteration order = file order = lifecycle order."""
    ordered: list[Phase]

    def by_id(self, phase_id: str) -> Phase:
        for p in self.ordered:
            if p.id == phase_id:
                return p
        raise KeyError(f"unknown phase: {phase_id!r}")

    def track_phases(self, track: str) -> list[Phase]:
        """The phases a ticket of `track` can visit, in lifecycle order. The order comes
        from the rule table (rules.py), not from this file."""
        by_id = {p.id: p for p in self.ordered}
        return [by_id[pid] for pid in _rules.lane_phase_ids(track) if pid in by_id]


# --- parsing ------------------------------------------------------------------

def _load_raw(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"phases.yml not found at {path}")
    parsed = _yaml_parse(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or "phases" not in parsed:
        raise ValueError("phases.yml: expected top-level mapping with key 'phases'")
    return parsed


def _build_phase(d: dict) -> Phase:
    pid = d.get("id")
    if not pid or not isinstance(pid, str):
        raise ValueError("phase entry missing string id")
    # Tolerant of the pre-KLC-179 shape `work: {prompt: ...}` (fixture trees, old overrides).
    legacy_work = d.get("work") if isinstance(d.get("work"), dict) else {}
    prompt = d.get("prompt") or legacy_work.get("prompt") or ""
    raw_picks = d.get("picks") or []
    if not isinstance(raw_picks, list) or not all(isinstance(x, str) and x for x in raw_picks):
        raise ValueError(f"phase {pid!r}: picks must be a list of labels")
    fact = _rules.PHASE_FACT.get(pid)
    picks = []
    for i, label in enumerate(raw_picks, start=1):
        forward = _rules.pick_is_forward(label)
        decision = (not forward) or fact in _DECISION_FACTS
        picks.append(Pick(id=i, label=label, forward=forward,
                          gate="decision" if decision else "conditional"))
    inputs = d.get("inputs") or []
    outputs = d.get("outputs") or []
    if not isinstance(inputs, list) or not isinstance(outputs, list):
        raise ValueError(f"phase {pid!r}: inputs/outputs must be lists")
    return Phase(
        id=pid,
        prompt=prompt,
        pick_required=bool(picks) and bool(d.get("pick_required", True)),
        picks=picks,
        inputs=list(inputs),
        outputs=list(outputs),
    )


_CACHE: Phases | None = None


def load_phases(force: bool = False) -> Phases:
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    path = framework_root() / "config" / "phases.yml"
    raw = _load_raw(path)
    seq = raw.get("phases") or []
    if not isinstance(seq, list) or not seq:
        raise ValueError("phases.yml: 'phases' must be a non-empty list")

    phases = [_build_phase(p) for p in seq]
    ids = [p.id for p in phases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"phases.yml: duplicate phase ids: {ids}")
    _CACHE = Phases(ordered=phases)
    return _CACHE


# --- state helpers ------------------------------------------------------------

def is_terminal(phase_value: str) -> bool:
    """True iff the meta.phase string is a terminal pseudo-state that no phase
    owns (`archived` or `cancelled`). The single gate every consumer that must
    refuse-to-advance / render-as-finished should use (KLC-076)."""
    return phase_value in TERMINAL_STATES


def parse_state(state: str) -> tuple[str, str]:
    """Split `<phase>:<state>` into (phase_id, state). Accepts the terminal
    sentinels `archived`/`cancelled` as ('archived','archived') /
    ('cancelled','cancelled') — never raises on a recognised terminal."""
    if state in TERMINAL_STATES:
        return (state, state)
    if ":" not in state:
        raise ValueError(f"invalid state {state!r}; expected '<phase>:<state>'")
    pid, st = state.split(":", 1)
    if st not in VALID_STATES:
        raise ValueError(f"invalid state suffix {st!r} in {state!r}")
    return (pid, st)


def format_state(phase_id: str, state: str) -> str:
    if phase_id in TERMINAL_STATES:
        return phase_id
    if state not in VALID_STATES:
        raise ValueError(f"invalid state {state!r}")
    return f"{phase_id}:{state}"


# Position ordering within a track: work < ack-needed < ack per phase, and
# `archived` past every real phase-state. This is THE single ordering formula,
# shared by epic_deps.reached() (the upstream "reached the point" milestone
# check) and epic_view (the downstream "has entered this phase's :work" check),
# so the epic view and the live `:work` enforcement can never silently desync
# on ordering (KLC-078 LOW-1). One formula, one rank map.
_POSITION_STATE_RANK = {STATE_WORK: 0, STATE_ACK_NEEDED: 1, STATE_ACK: 2}
POSITION_ARCHIVED = 10 ** 6


def position(track: str, phase_state: str) -> int | None:
    """A comparable integer position for `phase_state` within `track`.

    Returns None when the position is unresolvable/meaningless:
      - `cancelled` (terminated early — reaches no real milestone);
      - a phase not applicable to the track;
      - a malformed state string.
    `archived` returns `POSITION_ARCHIVED`, past every real phase-state."""
    if phase_state == STATE_ARCHIVED:
        return POSITION_ARCHIVED
    if phase_state == STATE_CANCELLED:
        return None
    try:
        pid, st = parse_state(phase_state)
    except ValueError:
        return None
    seq = _rules.lane_phase_ids(track)
    if pid == "observe" and pid not in seq and "learn" in seq:
        # A legacy S ticket can still stand at observe (it left the light lane in KLC-179):
        # rank it where it always was, just before learn, so epic milestones keep working.
        seq = seq[:seq.index("learn")] + ["observe"] + seq[seq.index("learn"):]
    if pid not in seq:
        return None
    return seq.index(pid) * 3 + _POSITION_STATE_RANK.get(st, 0)


# --- CLI for debugging --------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Inspect phases.yml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all phases")
    p2 = sub.add_parser("track", help="list phases for a track")
    p2.add_argument("--track", required=True, choices=TRACK_ORDER)
    p3 = sub.add_parser("show", help="show one phase")
    p3.add_argument("--id", required=True)
    args = ap.parse_args(argv)

    ph = load_phases()
    if args.cmd == "list":
        for p in ph.ordered:
            print(f"{p.id:<22} tracks={','.join(p.tracks):<12} "
                  f"prompt={p.prompt or '-'}")
        return 0
    if args.cmd == "track":
        for p in ph.track_phases(args.track):
            print(p.id)
        return 0
    if args.cmd == "show":
        p = ph.by_id(args.id)
        import json
        print(json.dumps({
            "id": p.id, "tracks": p.tracks, "prompt": p.prompt,
            "pick_required": p.pick_required,
            "picks": [{"id": pk.id, "label": pk.label, "gate": pk.gate}
                      for pk in p.picks],
            "inputs": p.inputs, "outputs": p.outputs,
        }, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
