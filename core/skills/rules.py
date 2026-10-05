"""rules.py — the facts model and the ordered rule table (KLC-179).

A ticket's progress is a set of facts (spec approved, steps green, merged, ...).
`next_move` looks at the facts of a lane and answers "what is the first missing
one?". That replaces walking the 14-phase x 4-track matrix of phases.yml.
This module is pure: no I/O except `derive_facts`, which may read
`review-report.md` when it is given a ticket directory, and never writes.

Lanes: `light` (legacy tracks XS and S) and `full` (M and L).

```text
full : spec_approved -> test_plan_approved -> design_approved -> plan_reviewed
       -> steps_green -> review_verdict -> manual_passed* -> merged
       -> observed* -> retro_written
light: spec_approved -> plan_reviewed -> steps_green -> review_verdict
       -> merged -> retro_written**
  *  manual: full lane with any risk tag; observed: full lane with user-facing, data,
     security or migration
  ** only on an overrun or a regression (facts.retro_required)
```

[!DECISION D-001] `plan_reviewed` comes AFTER `design_approved` on the full
lane: design writes the impl-plan there, while on light the plan is written
together with the spec. FACT_ORDER and the rule table agree on this.

Human decision points (a move with `stop=True`, the only `--pick` stops):
`spec_approved` on both lanes, `design_approved` on full, and `manual_passed` on full
when risk tags make the manual check run. A decision fact is written ONLY by the human's
approving pick (`lifecycle.apply_ack`), never by a gate: the gate at work -> ack-needed
leaves it missing, so `blocked_on` shows at `<phase>:ack-needed` and a lane switch cannot
jump past the pick. The facts of `integrate`, `observe` and `learn` are ack-time facts too
(the gate cannot know them); `merged` additionally needs the merge check of `gate_policy`.
`observe` runs for the four tags user-facing, data, security and migration; `manual` for any tag.

Unusual choices, kept on purpose:
  - Fail closed. A fact holds only when it is exactly `True` (or, for
    `review_verdict`, an `APPROVED...` string). Anything else counts as missing,
    so a malformed value can never skip a gate.
  - An unknown track runs as `full` (more gates, never fewer).
  - `archive` is returned only when every required fact holds.
  - Legacy derivation treats a `skipped` phase as satisfied: "not required" and
    "done" look the same to the rule table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

FACT_ORDER = ("spec_approved", "test_plan_approved", "design_approved", "plan_reviewed",
              "steps_green", "review_verdict", "manual_passed", "merged",
              "observed", "retro_written")
FACTS = frozenset(FACT_ORDER)

LIGHT, FULL = "light", "full"
DECISION_FACTS = {LIGHT: ("spec_approved",),
                  FULL: ("spec_approved", "design_approved", "manual_passed")}
# Facts only the ack establishes (the gate cannot know them): see `lifecycle._record_ack_facts`.
ACK_TIME_FACTS = {"manual": "manual_passed", "integrate": "merged",
                  "observe": "observed", "learn": "retro_written"}
OBSERVE_TAGS = frozenset({"user-facing", "data", "security", "migration"})


@dataclass(frozen=True)
class Move:
    """The next step. `stop` is true when a human decision (--pick) is needed."""
    action: str                     # spec|test-plan|design|plan-review|build|review|manual|
    #                                 integrate|observe|retro|archive|done
    phase: str | None = None        # phases.yml id that does the work (None for done)
    reason: str = ""
    stop: bool = False
    fact: str | None = None         # the missing fact this move produces

    @property
    def blocked_on(self) -> str | None:
        return self.fact if self.stop else None


# --- lanes ----------------------------------------------------------------

def legacy_track(track) -> str:
    """Legacy track letter -> lane. XS/S are light; M/L and anything unknown are full."""
    return LIGHT if track in ("XS", "S") else FULL


def lane_letter(lane: str) -> str:
    """Mirror of `legacy_track` for the derived `meta.track` value (light -> S, full -> M)."""
    return "S" if lane == LIGHT else "M"


def _lane(track) -> str:
    return track if track in (LIGHT, FULL) else legacy_track(track)


def lane_of(meta: dict) -> str:
    """The lane of a ticket meta: `facts.track` when it is a lane, else the legacy letter."""
    facts = meta.get("facts") if isinstance(meta, dict) else None
    track = facts.get("track") if isinstance(facts, dict) else None
    if track in (LIGHT, FULL):
        return track
    return legacy_track(meta.get("track") if isinstance(meta, dict) else None)


# --- fact values ------------------------------------------------------------

def holds(facts: dict, name: str) -> bool:
    """True only for a well-formed, satisfied fact; malformed values are missing."""
    value = facts.get(name) if isinstance(facts, dict) else None
    if name == "review_verdict":
        return value is True or (isinstance(value, str) and value.upper().startswith("APPROVED"))
    return value is True


def if_approved(facts: dict, phase_id: str, track) -> dict:
    """The facts as the approving pick of `phase_id` would leave them. A decision fact
    is written only by that pick, so a read of a ticket standing at `<phase>:ack-needed`
    (where does an ack go next?) must assume it; other facts are returned unchanged."""
    out = dict(facts) if isinstance(facts, dict) else {}
    fact = PHASE_FACT.get(phase_id)
    if fact and fact in DECISION_FACTS[_lane(track)] and fact not in out:
        out[fact] = True
    return out


def _has_tags(risk_tags) -> frozenset:
    """The ticket's risk tags, lowercased (an empty set when there are none)."""
    if not risk_tags or isinstance(risk_tags, bool):
        return frozenset()
    if isinstance(risk_tags, str):
        risk_tags = [risk_tags]
    return frozenset(str(t).lower() for t in risk_tags)


# --- the rule table -----------------------------------------------------------
# (fact, applies(lane, facts, has_tags), action, phase on light, phase on full)
# The order IS FACT_ORDER; the first required-and-missing fact wins.

def _always(lane, facts, tags): return True
def _full_only(lane, facts, tags): return lane == FULL
def _with_tags_full(lane, facts, tags): return lane == FULL and bool(tags)
def _observe(lane, facts, tags): return lane == FULL and bool(tags & OBSERVE_TAGS)
def _retro(lane, facts, tags): return lane == FULL or facts.get("retro_required") is True

_ALL_TAGS = OBSERVE_TAGS | {"any"}      # lane_phase_ids lists the superset of phases

_Rule = tuple[str, Callable, str, str, str]
RULES: tuple[_Rule, ...] = (
    ("spec_approved",      _always,         "spec",        "discovery-lite",       "discovery"),
    ("test_plan_approved", _full_only,      "test-plan",   "acceptance-test-plan", "acceptance-test-plan"),
    ("design_approved",    _full_only,      "design",      "design",               "design"),
    ("plan_reviewed",      _always,         "plan-review", "discovery-lite",       "design"),
    ("steps_green",        _always,         "build",       "build",                "build"),
    ("review_verdict",     _always,         "review",      "review",               "review"),
    ("manual_passed",      _with_tags_full, "manual",      "manual",               "manual"),
    ("merged",             _always,         "integrate",   "integrate",            "integrate"),
    ("observed",           _observe,        "observe",     "observe",              "observe"),
    ("retro_written",      _retro,          "retro",       "learn",                "learn"),
)
assert tuple(r[0] for r in RULES) == FACT_ORDER


def required_facts(facts: dict, track, *, risk_tags=None) -> list[str]:
    """The facts this ticket needs before it can archive, in FACT_ORDER (what `klc status` lists)."""
    facts = facts if isinstance(facts, dict) else {}
    lane, tags = _lane(track), _has_tags(risk_tags)
    return [r[0] for r in RULES if r[1](lane, facts, tags)]


def lane_phase_ids(track) -> list[str]:
    """Every phase a ticket of this track can visit, in lifecycle order (intake first).

    A superset: `manual`/`observe` (risk tags) and `learn` on light (overrun) are
    listed although a given ticket may skip them. `next_move` makes the exact call."""
    lane = _lane(track)
    out = ["intake"]
    for fact, applies, _action, light_phase, full_phase in RULES:
        if not applies(lane, {"retro_required": True}, _ALL_TAGS):
            continue
        pid = light_phase if lane == LIGHT else full_phase
        if pid not in out:
            out.append(pid)
    return out


def phase_applies(phase_id: str, meta: dict) -> bool:
    """False when the rule table would never enter `phase_id` for this ticket
    (a lane without it, or `manual`/`observe`/`learn` not demanded)."""
    lane = lane_of(meta)
    facts = meta.get("facts") if isinstance(meta.get("facts"), dict) else {}
    tags = _has_tags(meta.get("risk_tags"))
    facts = {**facts, "retro_required": facts.get("retro_required") or retro_required(meta)}
    if phase_id == "intake":
        return True
    for _fact, applies, _action, light_phase, full_phase in RULES:
        if (light_phase if lane == LIGHT else full_phase) == phase_id and applies(lane, facts, tags):
            return True
    return False


def phases_from(fact: str, track) -> list[str]:
    """The phases of the facts `fact` and every later one, in lifecycle order (a phase
    owns a fact when it is the rule table's phase for it on this lane)."""
    lane = _lane(track)
    out: list[str] = []
    for name in FACT_ORDER[FACT_ORDER.index(fact):]:
        rule = next(r for r in RULES if r[0] == name)
        pid = rule[3] if lane == LIGHT else rule[4]
        if pid not in out:
            out.append(pid)
    return out

_SUB_STATES = ("work", "ack-needed", "ack")


def phase_for(facts: dict, state_hint: str = "work", *, track=None, risk_tags=None) -> str:
    """The legacy `meta.phase` string (`<phase>:<state>`) a set of facts stands for.

    `state_hint` is one of work / ack-needed / ack, or `<phase>:<state>` for the
    ack-time phases (manual / integrate / observe / learn). The sub-states are not
    facts, so the caller (the one that knows which state it is entering) says which;
    for an ack-time phase the facts alone cannot tell `review:ack-needed` from
    `integrate:ack-needed` (their fact is written only at the ack), so the caller names
    the phase and it is honoured only when it is the phase of the next missing fact.
    `work` names the phase of the next missing fact. `ack-needed` and `ack` name the
    phase of the last fact that is PRESENT (a verdict like CHANGES_REQUESTED counts
    as present: the review phase is still the one waiting for its ack).
    Terminal tickets map to `archived` / `cancelled`. `track` defaults to
    `facts["track"]`; the table needs `risk_tags` (not a fact) for manual/observe."""
    facts = facts if isinstance(facts, dict) else {}
    named = None
    if isinstance(state_hint, str) and ":" in state_hint:
        named, state_hint = state_hint.split(":", 1)
    hint = state_hint if state_hint in _SUB_STATES else "work"
    if facts.get("terminal") in ("archived", "cancelled"):
        return facts["terminal"]
    lane_track = track if track is not None else facts.get("track")
    move = next_move(facts, lane_track, risk_tags=risk_tags)
    if (named in ACK_TIME_FACTS and hint != "work" and move.phase == named
            and move.action not in ("archive", "done")):
        return f"{named}:{hint}"
    if hint == "work":
        return "archived" if move.action in ("archive", "done") else f"{move.phase}:work"
    lane = _lane(lane_track)
    tags = _has_tags(risk_tags)
    last = None
    for fact, applies, _action, light_phase, full_phase in RULES:
        if applies(lane, facts, tags) and fact in facts:
            last = light_phase if lane == LIGHT else full_phase
    if last is None:
        last = move.phase if move.phase and move.action not in ("archive", "done") else "intake"
    return f"{last}:{hint}"


def gate_facts(phase_id: str, ticket_dir=None) -> dict:
    """Facts a phase's passing gate establishes (empty for a phase without one).

    `review` / `review-lite` read the verdict from review-report.md; with no readable
    verdict they establish nothing (fail closed). The decision facts (spec, design) and the
    ack-time facts (manual, merged, observed, retro) are NOT established here: the human's
    pick (or, for `merged`, the merge check plus the ack) writes them. The plan is final
    once its phase (or build) is done, so `plan_reviewed` still rides the gate."""
    fact = PHASE_FACT.get(phase_id)
    if fact is None or phase_id in ACK_TIME_FACTS:
        return {}
    if fact == "review_verdict":
        verdict = report_verdict(ticket_dir) if ticket_dir is not None else None
        return {"review_verdict": verdict} if verdict else {}
    out = {} if fact in ("spec_approved", "design_approved") else {fact: True}
    if phase_id in ("discovery-lite", "design") or fact == "steps_green":
        out["plan_reviewed"] = True
    return out


# Picks whose phases' files are removed (KLC-176 supersede). `needs-rework` revises in
# place, `extract-to-claudemd` and `force-full-discovery` have nothing to remove.
_SUPERSEDING = frozenset({"upgrade-to-full", "revise-impl-plan", "request-changes", "failed",
                          "regression", "rollback"})


@dataclass(frozen=True)
class PickPlan:
    """What a non-approving pick does: the lane after it, the facts that remain, the
    phase `<target>:work` it enters and the phases whose files are superseded."""
    lane: str
    facts: dict
    target: str
    supersede: list


def pick_plan(facts: dict, label: str, phase_id: str, track, *, risk_tags=None) -> PickPlan:
    """Plan a rework / route pick (replaces the goto and supersede lists of phases.yml).

    The pick clears the fact it undoes and every later one (`clear_from`), possibly
    switches the lane, and the target is whatever the rule table then finds missing.
    The files removed are those of the phases of the cleared facts that lie at or before
    `phase_id`, never `build` (its `build/steps.json` is the progress of the work being
    redone), so each old supersede list is reproduced:
    review -> [review], manual failed -> [review, manual], regression and rollback ->
    [review, manual, integrate, observe], revise-impl-plan -> [design],
    upgrade-to-full -> [discovery-lite]."""
    lane = _lane(track)
    after = dict(facts) if isinstance(facts, dict) else {}
    if label in ("upgrade-to-full", "force-full-discovery"):
        cleared = "spec_approved"
        new_lane = FULL
    elif label == "extract-to-claudemd":
        cleared, new_lane = "retro_written", lane
    elif label in _REWORK_FROM:
        cleared, new_lane = _REWORK_FROM[label] or PHASE_FACT.get(phase_id), lane
    else:
        raise ValueError(f"{label!r} is not a rework or route pick")
    if cleared:
        clear_from(after, cleared)
    after["track"] = new_lane
    move = next_move(after, new_lane, risk_tags=risk_tags)
    target = move.phase if move.action not in ("archive", "done") and move.phase else phase_id
    supersede: list[str] = []
    if label in _SUPERSEDING and cleared:
        order = lane_phase_ids(lane)
        limit = order.index(phase_id) if phase_id in order else len(order) - 1
        supersede = [p for p in phases_from(cleared, lane)
                     if p != "build" and p in order and order.index(p) <= limit]
    return PickPlan(new_lane, after, target, supersede)


def retro_required(meta: dict) -> bool:
    """Today's detection: a regression, or any overrun of rework counts or budgets."""
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("regression_observed") in (1, True) or _any_overrun(meta.get("rework_count"))
                or _any_overrun(meta.get("budgets")))


def next_move(facts: dict, track, *, risk_tags=None) -> Move:
    """The first missing required fact of the lane, or `archive` when none is."""
    facts = facts if isinstance(facts, dict) else {}
    if facts.get("terminal") in ("archived", "cancelled"):
        return Move("done", None, f"ticket is {facts['terminal']}")
    lane = _lane(track)
    tags = _has_tags(risk_tags)
    for fact, applies, action, light_phase, full_phase in RULES:
        if not applies(lane, facts, tags) or holds(facts, fact):
            continue
        phase = light_phase if lane == LIGHT else full_phase
        value = facts.get(fact)
        if fact == "review_verdict" and isinstance(value, str) and value and not holds(facts, fact):
            # a verdict that is not an approval sends the ticket back to build
            return Move("build", "build", f"review verdict {value}: rework", False, "steps_green")
        return Move(action, phase, f"missing fact: {fact}", fact in DECISION_FACTS[lane], fact)
    return Move("archive", "archived", "every required fact holds")


# --- derivation from legacy metas ------------------------------------------------

PHASE_FACT = {
    "discovery-lite": "spec_approved", "discovery": "spec_approved",
    "acceptance-test-plan": "test_plan_approved", "design": "design_approved",
    "xs-build": "steps_green", "build": "steps_green",
    "review-lite": "review_verdict", "review": "review_verdict",
    "manual": "manual_passed", "integrate": "merged",
    "observe": "observed", "learn": "retro_written",
}
# A rework pick does not approve; it clears this fact and every later one.
_REWORK_FROM = {
    "needs-rework": None,          # the phase's own fact
    "request-changes": "steps_green",
    "failed": "steps_green",
    "regression": "steps_green",
    "rollback": "steps_green",     # the rolled-back code goes through build and review again
    "revise-impl-plan": "design_approved",
}
REWORK_LABELS = frozenset(_REWORK_FROM)
# Picks that change the route or loop a phase, not approve it and not redo earlier work.
ROUTE_LABELS = frozenset({"upgrade-to-full", "force-full-discovery", "extract-to-claudemd"})


def pick_is_forward(label: str) -> bool:
    """True for a pick that approves (the ticket moves to the next missing fact)."""
    return label not in REWORK_LABELS and label not in ROUTE_LABELS
_NOTE_PICK = re.compile(r"pick=\d+:([\w-]+)")
_VERDICT = re.compile(r"^#+\s*Verdict:\s*([A-Za-z_ ]+?)\s*$", re.M)


def _pick_label(entry: dict) -> str:
    pick = entry.get("pick")
    if isinstance(pick, dict) and isinstance(pick.get("label"), str):
        return pick["label"]
    m = _NOTE_PICK.search(entry.get("note") or "") if isinstance(entry.get("note"), str) else None
    return m.group(1) if m else ""


def clear_from(facts: dict, fact: str) -> None:
    for name in FACT_ORDER[FACT_ORDER.index(fact):]:
        facts.pop(name, None)


def _phase_id(value) -> str:
    return value.split(":", 1)[0] if isinstance(value, str) else ""


def report_verdict(ticket_dir) -> str | None:
    try:
        text = (Path(ticket_dir) / "review-report.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    found = _VERDICT.findall(text)
    return found[-1].strip().upper().replace(" ", "_") if found else None


def derive_facts(meta: dict, ticket_dir=None) -> dict:
    """Facts of a ticket. A meta with a `facts` dict returns a copy of it; an
    older meta is replayed from `phase_history`. Never mutates or writes."""
    if not isinstance(meta, dict):
        return {}
    existing = meta.get("facts")
    if isinstance(existing, dict):
        return dict(existing)

    facts: dict = {}
    history = meta.get("phase_history")
    history = [h for h in history if isinstance(h, dict)] if isinstance(history, list) else []
    for entry in history:
        value = entry.get("phase")
        pid = _phase_id(value)
        event = entry.get("event")
        if event == "skipped" and pid in PHASE_FACT:
            facts[PHASE_FACT[pid]] = True            # not required == satisfied
        elif isinstance(value, str) and value.endswith(":ack") and event == "ack" and pid in PHASE_FACT:
            fact, label = PHASE_FACT[pid], _pick_label(entry)
            if label in _REWORK_FROM:
                clear_from(facts, _REWORK_FROM[label] or fact)
            else:
                facts[fact] = "APPROVED" if fact == "review_verdict" else True
        if pid in ("build", "xs-build"):
            facts["plan_reviewed"] = True             # the plan is reviewed before build starts
        if pid == "xs-build":
            facts.setdefault("spec_approved", True)   # the XS fast-track had no spec gate
    if "steps_green" in facts:
        facts["plan_reviewed"] = True

    facts["track"] = legacy_track(meta.get("track"))
    phase = meta.get("phase")
    if phase == "cancelled" or meta.get("cancelled"):
        facts["terminal"] = "cancelled"
        facts.pop("merged", None)
        return facts
    if phase == "archived":
        facts["terminal"] = "archived"
        facts["merged"] = True
    elif isinstance(meta.get("integrate"), dict) and meta["integrate"]:
        facts["merged"] = True
    if not facts.get("terminal"):
        _imply_by_position(facts, meta)
    if ticket_dir is not None and "review_verdict" in facts:
        verdict = report_verdict(ticket_dir)
        if verdict:
            facts["review_verdict"] = verdict
    if retro_required(meta):
        facts["retro_required"] = True
    return facts


def _imply_by_position(facts: dict, meta: dict) -> None:
    """A live legacy ticket stands at a phase, so the phases before it are done.

    History replay is the primary source, but an older or hand-moved meta may lack the
    ack entries (a ticket jumped forward, a truncated history). Standing at `build:work`
    means the spec was approved; standing at `review:ack` means the build gate passed
    too. This only ADDS facts for phases strictly before the current one, plus the
    facts of the current phase once it is at `:ack`; it never clears one, so a rework in
    the history (which cleared facts) is not undone for the phase being redone."""
    value = meta.get("phase")
    try:
        pid, state = value.split(":", 1)
    except (AttributeError, ValueError):
        return
    lane = legacy_track(meta.get("track"))
    order = lane_phase_ids(lane)
    if pid == "observe" and pid not in order and "learn" in order:
        here = order.index("learn")        # a legacy S ticket standing at observe (just before learn)
    elif pid in order:
        here = order.index(pid)
    else:
        return
    for fact, _applies, _action, light_phase, full_phase in RULES:
        owner = light_phase if lane == LIGHT else full_phase
        idx = order.index(owner) if owner in order else None
        if idx is None or fact in facts:
            continue
        if idx < here or (idx == here and state == "ack"):
            facts[fact] = "APPROVED" if fact == "review_verdict" else True


def _any_overrun(value) -> bool:
    return isinstance(value, dict) and any(isinstance(v, (int, float)) and v > 0 for v in value.values())
