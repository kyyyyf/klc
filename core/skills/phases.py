#!/usr/bin/env python3
"""phases.py — data-driven state machine over config/phases.yml.

The klc CLI (next / ack / jump / abort / status) holds no knowledge of
phase names. This module is the only place that loads phases.yml and
interprets it. Everything else asks:

    ph = load_phases()
    ph.next_phase(track="M", phase_id="design")

States per phase: `<id>:work`, `<id>:ack-needed`, `<id>:ack`. Plus two
terminal pseudo-states that no phase owns: `archived` (the ticket finished
its lifecycle — "done") and `cancelled` (the ticket was terminated early and
will never be done — NOT counted as completed work; see KLC-076).

YAML parser is a small subset tailored to the shape of phases.yml:
  - top-level mapping;
  - lists of mappings;
  - string scalars (quoted or bare), bool, null, integer;
  - nested lists inside a mapping (e.g. tracks: [XS, S, M, L]).

PyYAML is a hard dep of nothing else in the framework; we keep it out.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root  # noqa: E402
from core.shared.yaml import parse as _yaml_parse  # noqa: E402


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

_GATES = {"auto", "conditional", "decision"}


@dataclass
class Pick:
    id:    int
    label: str
    goto:  str                 # "next" or "<phase>:work"
    supersede: list[str] = field(default_factory=list)
    gate: str = "decision"


@dataclass
class Phase:
    id:            str
    tracks:        list[str]
    prompt:        str
    auto_to_ack:   bool
    pick_required: bool
    picks:         list[Pick]
    pick_records_to: str | None
    inputs:        list[str]
    outputs:       list[str]
    auto_ack_after: str | None
    condition:     str | None = None   # e.g. "meta.risk_tags in ['security']"

    def pick_by_id(self, pick_id: int) -> Pick | None:
        for p in self.picks:
            if p.id == pick_id:
                return p
        return None

    def should_run(self, meta: dict) -> bool:
        """Evaluate condition against meta. Returns True if phase should run.

        Supported expression forms:
          meta.<dotted.path> in ['v1', 'v2']
          meta.<dotted.path> not in ['v1', 'v2']
          meta.<dotted.path> == value
          meta.<dotted.path> > N
          meta.<dotted.path> >= N
          meta.<dotted.path> any_overrun   (true if any value in dict > 0)
        """
        if self.condition is None:
            return True
        return _eval_condition(self.condition, meta)


@dataclass
class Phases:
    """The loaded model. Iteration order = file order = lifecycle order."""
    ordered: list[Phase]

    def by_id(self, phase_id: str) -> Phase:
        for p in self.ordered:
            if p.id == phase_id:
                return p
        raise KeyError(f"unknown phase: {phase_id!r}")

    def track_phases(self, track: str) -> list[Phase]:
        """Ordered list of phases that apply to the given track."""
        return [p for p in self.ordered if track in p.tracks]

    def next_phase(self, track: str, phase_id: str) -> Phase | None:
        """The next phase in the track after `phase_id`. Returns None
        if phase_id is the last one for this track (→ archived)."""
        seq = self.track_phases(track)
        ids = [p.id for p in seq]
        if phase_id not in ids:
            return None
        idx = ids.index(phase_id)
        return seq[idx + 1] if idx + 1 < len(seq) else None

    def prev_phase(self, track: str, phase_id: str) -> Phase | None:
        """The previous phase in the track before `phase_id`. None if first."""
        seq = self.track_phases(track)
        ids = [p.id for p in seq]
        if phase_id not in ids:
            return None
        idx = ids.index(phase_id)
        return seq[idx - 1] if idx > 0 else None


# --- condition evaluator ------------------------------------------------------

def _get_nested(meta: dict, path: str):
    """Traverse dotted path in meta dict. Returns None if not found."""
    parts = path.split(".")
    cur = meta
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _eval_condition(expr: str, meta: dict) -> bool:
    """Evaluate a condition expression against a meta dict.

    Grammar (whitespace-insensitive):
      meta.<path> in [<quoted-list>]
      meta.<path> not in [<quoted-list>]
      meta.<path> == <value>
      meta.<path> > <number>
      meta.<path> >= <number>
      meta.<path> any_overrun
      <cond> OR <cond>
    """
    import re as _re

    expr = expr.strip()

    # OR combinator (short-circuit)
    if " OR " in expr:
        parts = expr.split(" OR ")
        return any(_eval_condition(p.strip(), meta) for p in parts)

    # meta.<path> in ['a', 'b', ...]
    m = _re.match(
        r"meta\.([a-z_A-Z0-9.]+)\s+(not\s+in|in)\s+\[([^\]]*)\]", expr
    )
    if m:
        path, op, raw_vals = m.group(1), m.group(2).strip(), m.group(3)
        vals = {v.strip().strip("'\"") for v in raw_vals.split(",")}
        value = _get_nested(meta, path)
        if isinstance(value, list):
            overlap = set(value) & vals
        else:
            overlap = {str(value)} & vals if value is not None else set()
        if op == "in":
            return bool(overlap)
        else:  # not in
            return not bool(overlap)

    # meta.<path> any_overrun
    m = _re.match(r"meta\.([a-z_A-Z0-9.]+)\s+any_overrun", expr)
    if m:
        value = _get_nested(meta, m.group(1))
        if isinstance(value, dict):
            return any(v > 0 for v in value.values() if isinstance(v, (int, float)))
        return False

    # meta.<path> >= N  or  meta.<path> > N
    m = _re.match(r"meta\.([a-z_A-Z0-9.]+)\s*(>=|>|==)\s*(\S+)", expr)
    if m:
        path, op, raw = m.group(1), m.group(2), m.group(3)
        value = _get_nested(meta, path)
        try:
            threshold = int(raw)
            lhs = int(value) if value is not None else 0
        except (ValueError, TypeError):
            return False
        if op == ">":
            return lhs > threshold
        if op == ">=":
            return lhs >= threshold
        if op == "==":
            return lhs == threshold

    # Fallback: unknown expression → always run (safe default)
    return True


def _is_known_condition(expr: str) -> bool:
    """Return True if the expression matches at least one known grammar pattern.

    Used by validate_config to detect typos in condition: fields.
    Runtime stays fail-open (_eval_condition returns True); this is static
    validation only.
    """
    import re as _re

    expr = expr.strip()
    if not expr:
        return False

    # OR combinator — check each part
    if " OR " in expr:
        return all(_is_known_condition(p.strip()) for p in expr.split(" OR "))

    patterns = [
        r"meta\.[a-z_A-Z0-9.]+\s+(not\s+in|in)\s+\[[^\]]*\]",
        r"meta\.[a-z_A-Z0-9.]+\s+any_overrun",
        r"meta\.[a-z_A-Z0-9.]+\s*(>=|>|==)\s*\S+",
    ]
    return any(_re.fullmatch(pat, expr) for pat in patterns)


# --- parsing ------------------------------------------------------------------

def _load_raw(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"phases.yml not found at {path}")
    parsed = _yaml_parse(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or "phases" not in parsed:
        raise ValueError("phases.yml: expected top-level mapping with key 'phases'")
    return parsed


def _build_pick(d: dict, phase_id: str) -> Pick:
    try:
        pid = int(d["id"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"phase {phase_id!r}: pick missing integer id ({e})")
    label = d.get("label")
    if not label or not isinstance(label, str):
        raise ValueError(f"phase {phase_id!r} pick {pid}: missing label")
    goto = d.get("goto")
    if not goto or not isinstance(goto, str):
        raise ValueError(f"phase {phase_id!r} pick {pid}: missing goto")
    supersede = d.get("supersede") or []
    if not isinstance(supersede, list):
        raise ValueError(f"phase {phase_id!r} pick {pid}: supersede must be a list")
    gate = d.get("gate", "decision")
    if gate not in _GATES:
        raise ValueError(f"phase {phase_id!r} pick {pid}: bad gate {gate!r}")
    return Pick(id=pid, label=label, goto=goto, supersede=list(supersede), gate=gate)


def _build_phase(d: dict) -> Phase:
    pid = d.get("id")
    if not pid or not isinstance(pid, str):
        raise ValueError("phase entry missing string id")
    tracks = d.get("tracks") or []
    if not isinstance(tracks, list) or not all(isinstance(t, str) for t in tracks):
        raise ValueError(f"phase {pid!r}: tracks must be a list of strings")
    for t in tracks:
        if t not in TRACK_ORDER:
            raise ValueError(f"phase {pid!r}: unknown track {t!r}")

    work  = d.get("work") or {}
    prompt = work.get("prompt", "") or ""
    auto_to_ack = bool(work.get("auto_to_ack", False))

    ack = d.get("ack") or {}
    pick_required = bool(ack.get("pick_required", False))
    pick_records_to = ack.get("pick_records_to") or None
    raw_picks = ack.get("picks") or []
    if not isinstance(raw_picks, list):
        raise ValueError(f"phase {pid!r}: ack.picks must be a list")
    picks = [_build_pick(p, pid) for p in raw_picks]

    inputs  = d.get("inputs")  or []
    outputs = d.get("outputs") or []
    if not isinstance(inputs, list) or not isinstance(outputs, list):
        raise ValueError(f"phase {pid!r}: inputs/outputs must be lists")

    return Phase(
        id=pid,
        tracks=list(tracks),
        prompt=prompt,
        auto_to_ack=auto_to_ack,
        pick_required=pick_required,
        picks=picks,
        pick_records_to=pick_records_to,
        inputs=list(inputs),
        outputs=list(outputs),
        auto_ack_after=d.get("auto_ack_after") or None,
        condition=d.get("condition") or None,
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
    # sanity: unique ids
    ids = [p.id for p in phases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"phases.yml: duplicate phase ids: {ids}")

    # sanity: every goto pointer is resolvable
    id_set = set(ids)
    for p in phases:
        for pk in p.picks:
            if pk.goto == "next":
                continue
            if pk.goto == "archived":
                continue
            if ":" in pk.goto:
                target_id, state = pk.goto.split(":", 1)
                if target_id not in id_set:
                    raise ValueError(
                        f"phase {p.id!r} pick {pk.id}: goto references "
                        f"unknown phase {target_id!r}"
                    )
                if state not in VALID_STATES:
                    raise ValueError(
                        f"phase {p.id!r} pick {pk.id}: goto state {state!r} "
                        f"invalid; expected one of {sorted(VALID_STATES)}"
                    )
            else:
                raise ValueError(
                    f"phase {p.id!r} pick {pk.id}: goto must be 'next', "
                    f"'archived', or '<phase>:<state>'"
                )
            for sup in pk.supersede:
                if sup not in id_set:
                    raise ValueError(
                        f"phase {p.id!r} pick {pk.id}: supersede references "
                        f"unknown phase {sup!r}"
                    )

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
            "picks": [{"id": pk.id, "label": pk.label, "goto": pk.goto,
                       "supersede": pk.supersede} for pk in p.picks],
            "inputs": p.inputs, "outputs": p.outputs,
        }, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
