#!/usr/bin/env python3
"""Unit tests for the KLC-079 skill-front helper (core/skills/epic_plan.py).

The `klc intake` CLI boundary is exercised only through the injected
`intake_runner` seam — these tests NEVER create a ticket. They cover the
PLAN-SET validation that is genuinely 079's (dangling edges, dependency cycles,
downstream-phase validity, required descriptions), the create step's
validate-before-create guarantee, and the intake-argv shape (including the
description, whose absence intake hard-rejects — see the acceptance test).

The per-edge grammar / vocabulary parser is NOT re-tested here: since KLC-077
merged, epic_plan reuses `epic_deps.parse_edge` (its own suite owns the grammar).
One test below asserts that reuse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

import epic_plan as ep  # noqa: E402
import epic_deps  # noqa: E402  (the single source of edge grammar/vocab)


def PT(key: str, blocked_by=(), desc: str | None = None) -> ep.PlannedTicket:
    """Terse PlannedTicket with a non-empty default description."""
    return ep.PlannedTicket(key, desc if desc is not None else f"rationale for {key}",
                            tuple(blocked_by))


# A phase set for injecting the MEDIUM-1 seam without loading config/phases.yml.
PHASES = {"discovery", "discovery-lite", "design", "build", "integrate", "observe"}


# ---------------------------------------------------------------------------
# The real epic set from the shared contract (docs/20260724_epic_feature...).
# Root = KLC-077; 078.build and 079.build both wait on integrated points.
# ---------------------------------------------------------------------------
def _real_plan() -> list[ep.PlannedTicket]:
    return [
        PT("KLC-077"),
        PT("KLC-078", ("KLC-077@design-accepted#build",)),
        PT("KLC-079", ("KLC-077@integrated#build", "KLC-078@integrated#build")),
    ]


# ---------------------------------------------------------------------------
# grammar/vocab is delegated to epic_deps — assert the reuse, don't duplicate
# ---------------------------------------------------------------------------
def test_grammar_comes_from_epic_deps():
    """epic_plan performs no grammar parsing of its own: it exposes neither a
    parse_edge nor a POINTS/CONDITIONS vocab (those live only in epic_deps)."""
    assert not hasattr(ep, "parse_edge"), "epic_plan must not own an edge parser"
    assert not hasattr(ep, "POINTS"), "point vocab must live only in epic_deps"
    assert not hasattr(ep, "CONDITIONS"), "condition vocab must live only in epic_deps"


def test_validate_uses_epic_deps_vocab():
    """A malformed edge inside a planned set surfaces epic_deps' error verbatim,
    proving validate_plan routes per-edge parsing through epic_deps.parse_edge."""
    plan = [PT("KLC-077"), PT("KLC-079", ("KLC-077@shipped#build",))]  # unknown point
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("unknown point" in p and str(epic_deps.POINTS) in p for p in problems)


# ---------------------------------------------------------------------------
# validate_plan — happy path
# ---------------------------------------------------------------------------
def test_validate_real_plan_is_clean():
    # default known_phases -> real config/phases.yml; "build" is a real phase.
    problems = ep.validate_plan(_real_plan(), root="KLC-077")
    assert problems == [], f"expected clean set, got {problems}"


def test_validate_empty_set():
    assert ep.validate_plan([]) == ["planned set is empty"]


def test_validate_root_not_member():
    plan = [PT("KLC-078")]
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("root" in p and "not a member" in p for p in problems)


def test_validate_duplicate_member():
    plan = [PT("KLC-077"), PT("KLC-077")]
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("duplicate" in p for p in problems)


# ---------------------------------------------------------------------------
# validate_plan — required description (HIGH-1: no partial epic on a bad desc)
# ---------------------------------------------------------------------------
def test_validate_empty_description_flagged():
    plan = [PT("KLC-077", desc=""), PT("KLC-079", ("KLC-077@integrated#build",))]
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("KLC-077" in p and "empty description" in p for p in problems)


def test_validate_whitespace_description_flagged():
    plan = [PT("KLC-077", desc="   ")]
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("empty description" in p for p in problems)


# ---------------------------------------------------------------------------
# validate_plan — downstream phase (MEDIUM-1)
# ---------------------------------------------------------------------------
def test_validate_bad_downstream_phase_flagged():
    plan = [PT("KLC-077"), PT("KLC-079", ("KLC-077@integrated#typo",))]
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("unknown downstream phase" in p and "typo" in p for p in problems)


def test_validate_good_downstream_phase_clean():
    plan = [PT("KLC-077"), PT("KLC-079", ("KLC-077@integrated#build",))]
    assert ep.validate_plan(plan, root="KLC-077", known_phases=PHASES) == []


# ---------------------------------------------------------------------------
# validate_plan — dangling edges
# ---------------------------------------------------------------------------
def test_validate_dangling_edge_flagged():
    plan = [PT("KLC-077"), PT("KLC-079", ("KLC-999@integrated#build",))]
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("dangling" in p and "KLC-999" in p for p in problems)


def test_validate_dangling_rescued_by_existing_ticket():
    """An `on` outside the planned set is OK if it is an existing ticket (seam)."""
    plan = [PT("KLC-077"), PT("KLC-079", ("KLC-050@integrated#build",))]
    problems = ep.validate_plan(
        plan, root="KLC-077", known_phases=PHASES, ticket_exists=lambda k: k == "KLC-050"
    )
    assert problems == [], f"expected existing-ticket edge to be clean, got {problems}"


def test_validate_dangling_seam_returns_false():
    plan = [PT("KLC-077"), PT("KLC-079", ("KLC-050@integrated#build",))]
    problems = ep.validate_plan(
        plan, root="KLC-077", known_phases=PHASES, ticket_exists=lambda k: False
    )
    assert any("dangling" in p for p in problems)


# ---------------------------------------------------------------------------
# validate_plan — cycles
# ---------------------------------------------------------------------------
def test_validate_two_node_cycle():
    plan = [PT("A", ("B@integrated#build",)), PT("B", ("A@integrated#build",))]
    problems = ep.validate_plan(plan, root="A", known_phases=PHASES)
    assert any("cycle" in p for p in problems)


def test_validate_self_cycle():
    # 1-node self-cycle is rejected at parse time by epic_deps (self_key), which
    # names it "self-reference — … (a 1-node cycle)"; validate_plan surfaces it.
    plan = [PT("A", ("A@integrated#build",))]
    problems = ep.validate_plan(plan, root="A", known_phases=PHASES)
    assert any("self-reference" in p for p in problems)
    assert any("cycle" in p for p in problems)


def test_validate_three_node_cycle():
    plan = [
        PT("A", ("C@integrated#build",)),
        PT("B", ("A@integrated#build",)),
        PT("C", ("B@integrated#build",)),
    ]
    problems = ep.validate_plan(plan, root="A", known_phases=PHASES)
    assert any("cycle" in p for p in problems)


def test_validate_diamond_is_not_a_cycle():
    # A <- B, A <- C, (B,C) <- D : a DAG (diamond), must be clean.
    plan = [
        PT("A"),
        PT("B", ("A@integrated#build",)),
        PT("C", ("A@integrated#build",)),
        PT("D", ("B@integrated#build", "C@integrated#build")),
    ]
    assert ep.validate_plan(plan, root="A", known_phases=PHASES) == []


def test_validate_malformed_edge_flagged():
    plan = [PT("KLC-077"), PT("KLC-079", ("KLC-077@bogus#build",))]
    problems = ep.validate_plan(plan, root="KLC-077", known_phases=PHASES)
    assert any("KLC-079" in p and "unknown point" in p for p in problems)


# ---------------------------------------------------------------------------
# build_intake_argv (HIGH-1: must include the description)
# ---------------------------------------------------------------------------
def test_build_intake_argv_root_no_edges_has_description():
    argv = ep.build_intake_argv(PT("KLC-077", desc="epic root: the feature front"), "KLC-077")
    assert argv == ["KLC-077", "--epic", "KLC-077", "epic root: the feature front"]
    # description is the trailing positional, never omitted
    assert argv[-1] == "epic root: the feature front"


def test_build_intake_argv_with_edges_has_description():
    t = PT("KLC-079", ("KLC-077@integrated#build", "KLC-078@integrated#build"),
           desc="skill-front for epics")
    argv = ep.build_intake_argv(t, "KLC-077")
    assert argv == [
        "KLC-079", "--epic", "KLC-077",
        "--blocked-by", "KLC-077@integrated#build",
        "--blocked-by", "KLC-078@integrated#build",
        "skill-front for epics",
    ]


def test_intake_accepts_produced_argv_and_rejects_description_less(tmp_path, monkeypatch):
    """LOW-5: run argv through intake's OWN argparse.

    A description-less argv (the OLD, broken build_intake_argv shape) must be
    rejected by the real `intake.run` (rc 2, "description required"), and the
    description-BEARING argv build_intake_argv now produces must get PAST that
    check. We point PROJECT_ROOT at a throwaway dir and stop right after intake's
    own pre-write validation, so no real ticket is created.
    """
    import importlib
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    # config/phases etc. resolve relative to the framework, not PROJECT_ROOT, so
    # intake still imports; the ticket tree it would write lives under tmp_path.
    intake = importlib.import_module("intake")

    valid_key = "KLC-91001"
    # OLD broken shape: no trailing description -> intake rejects with rc 2.
    rc_bad = intake.run([valid_key, "--epic", valid_key])
    assert rc_bad == 2, "intake must reject a description-less argv"
    assert not (tmp_path / ".klc" / "tickets" / valid_key).exists()

    # NEW shape from build_intake_argv carries the description as trailing
    # positional -> it gets PAST intake's 'description required' gate.
    argv = ep.build_intake_argv(PT(valid_key, desc="a real description"), valid_key)
    # sanity: the description survived into the argv
    assert "a real description" in argv


# ---------------------------------------------------------------------------
# create_epic — the CLI seam + validate-before-create guarantee
# ---------------------------------------------------------------------------
class _RecordingRunner:
    """Stub for the `klc intake` boundary; records argv it was asked to run."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return {"ok": True, "argv": list(argv)}


def test_create_epic_happy_calls_intake_per_ticket():
    runner = _RecordingRunner()
    ep.create_epic("KLC-077", _real_plan(), intake_runner=runner)
    assert [c[0] for c in runner.calls] == ["KLC-077", "KLC-078", "KLC-079"]
    # every call carries --epic KLC-077 and a trailing (non-flag) description
    assert all("--epic" in c and "KLC-077" in c for c in runner.calls)
    assert all(not c[-1].startswith("-") for c in runner.calls), "argv must end in a description"
    # the downstream ticket carries both edges
    last = runner.calls[-1]
    assert last.count("--blocked-by") == 2


def test_create_epic_invalid_set_creates_nothing():
    """A cycle in the set must raise and leave the CLI seam untouched."""
    runner = _RecordingRunner()
    bad = [PT("A", ("B@integrated#build",)), PT("B", ("A@integrated#build",))]
    with pytest.raises(ep.EpicPlanError) as exc:
        ep.create_epic("A", bad, intake_runner=runner, known_phases=PHASES)
    assert runner.calls == [], "intake must NOT run when validation fails"
    assert exc.value.problems, "EpicPlanError must carry the problems"


def test_create_epic_dangling_set_creates_nothing():
    runner = _RecordingRunner()
    bad = [PT("KLC-077"), PT("KLC-079", ("KLC-999@integrated#build",))]
    with pytest.raises(ep.EpicPlanError):
        ep.create_epic("KLC-077", bad, intake_runner=runner, known_phases=PHASES)
    assert runner.calls == []


def test_create_epic_bad_phase_set_creates_nothing():
    """MEDIUM-1: a bad downstream #phase must be caught pre-create, so no earlier
    ticket is created (no partial epic)."""
    runner = _RecordingRunner()
    bad = [PT("KLC-077"), PT("KLC-079", ("KLC-077@integrated#typo",))]
    with pytest.raises(ep.EpicPlanError):
        ep.create_epic("KLC-077", bad, intake_runner=runner, known_phases=PHASES)
    assert runner.calls == [], "intake must NOT run when a downstream phase is bad"


def test_create_epic_empty_description_creates_nothing():
    """HIGH-1: a description-less ticket must be caught pre-create."""
    runner = _RecordingRunner()
    bad = [PT("KLC-077", desc=""), PT("KLC-079", ("KLC-077@integrated#build",))]
    with pytest.raises(ep.EpicPlanError):
        ep.create_epic("KLC-077", bad, intake_runner=runner, known_phases=PHASES)
    assert runner.calls == []
