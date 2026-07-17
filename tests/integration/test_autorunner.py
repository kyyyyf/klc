"""Tests for KLC-046: autonomous runner `klc run <KEY>`.

The runner is a thin driver over the existing skills (build_orchestrator,
runner, lifecycle, gate_policy) reusing the KLC-045 `ack --auto` path. It is
SINGLE-USER / feature-off only. These tests drive REAL lifecycle/`ack --auto`
with only agent dispatch faked (ZERO real agent calls) and assert genuine state
transitions, guardrail pauses, and the never-merge/never-push safety invariant.

Structure mirrors tests/integration/test_gate_policy.py (fixtures under
tmp_path/.klc, PROJECT_ROOT monkeypatched, phases cache flushed, and
collect_signals patched to bypass real signal I/O).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (_FW_ROOT, _FW_ROOT / "core" / "skills", _FW_ROOT / "core" / "phases"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_CLEAN_SIG = {
    "advisory": "",
    "scope_expansion": False,
    "sentinels": False,
    "mutation": False,
    "budget_overrun": False,
    "verdict": "APPROVED",
    "route_confidence": "high",
}


def _flush_phases_cache():
    import core.skills.phases as ph_mod
    ph_mod._CACHE = None
    import phases as ph_mod2  # the bare-import copy used by lifecycle/ack
    ph_mod2._CACHE = None


def _patch_clean_signals(monkeypatch, sig=None):
    """Patch gate_policy.collect_signals everywhere ack.py can see it."""
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(sig or _CLEAN_SIG))


def _modules_json(tmp_path: Path):
    idx = tmp_path / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(
        json.dumps({"modules": [{"name": "m", "src": ["core/x.py"], "tests": [], "phase": "stable"}]}),
        encoding="utf-8",
    )


_SPEC = (
    "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
    "## Goals\nDo thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
    "## Affected\nm: core/x.py, src=core/x.py:1\n"
    "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
)

_IMPL_PLAN = (
    "## step-1 — do the thing\n- **Goal:** implement\n- RED: not applicable\n"
    "- **Interfaces:** `def f() -> None`\n- **Expected:** f runs\n"
    "- **VERIFY:** pytest\n- **COMMIT:** {t} step-1: do the thing\n"
    "- **Affected:** core/x.py\n- **Code sketch:** not applicable\n"
)


def _make_ticket(tmp_path: Path, ticket: str, phase: str, track: str,
                 *, budgets=None, risk_tags=None) -> Path:
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": phase, "track": track,
        "route_confidence": "high", "affected_modules": ["m"], "layer": "code",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "budgets": budgets if budgets is not None else {"mutation_fix_attempts": 0},
        "risk_tags": risk_tags or [], "phase_history": [],
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(_SPEC.format(t=ticket), encoding="utf-8")
    (td / "impl-plan.md").write_text(_IMPL_PLAN.format(t=ticket), encoding="utf-8")
    _modules_json(tmp_path)
    return td


def _write_declared_output(td: Path, rel: str):
    """Simulate a real phase agent writing one declared output file per its card."""
    p = td / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if rel == "build-log.md":
        p.write_text("## Evidence\n\n```\n$ pytest\n1 passed\n```\n", encoding="utf-8")
    elif rel.endswith("options.md"):
        p.write_text("# Design\n## Option A\nADR_NEEDED=no REASON=\"minimal\"\n", encoding="utf-8")
    elif rel == "impl-plan.md":
        p.write_text(_IMPL_PLAN.format(t=td.name), encoding="utf-8")
    elif rel.endswith("review-report.md"):
        p.write_text("# Review\n\n## Findings\n\nNone.\n\n## Verdict\n\nAPPROVED\n", encoding="utf-8")
    else:
        p.write_text(f"# {rel}\n\ncontent\n", encoding="utf-8")


def _make_green_dispatch(td: Path, calls: list):
    """Fake dispatch that, like a real phase agent, writes the phase's DECLARED
    outputs (phases.yml outputs) itself and writes the response sink at out_path.
    Records each call (phase, prompt path, out path, track).

    Signature matches both call sites: build_orchestrator.run_build (per step)
    and autorunner._dispatch (per non-build phase, which now also passes ticket=).
    """
    import phases as _ph

    def fake(phase_id, prompt_path, out_path, *, track=None, ticket=None, **kw):
        calls.append({"phase": phase_id, "prompt": str(prompt_path),
                      "out": str(out_path), "track": track})
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# {phase_id} response\n\nGreen.\n", encoding="utf-8")
        for rel in (_ph.load_phases().by_id(phase_id).outputs or []):
            _write_declared_output(td, rel)
        return 0
    return fake


# ===========================================================================
# step-1: guardrail predicate (AC-4)
# ===========================================================================

def test_guardrail_integrate_pauses(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-G1", "integrate:work", "S")
    import autorunner
    reason = autorunner.guardrail("KLC-G1", "integrate", 0, cap=99)
    assert reason and ("integrate" in reason.lower() or "outward" in reason.lower()), reason


def test_guardrail_budget_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-G2", "build:work", "S",
                 budgets={"mutation_fix_attempts": 3})  # at DEFAULT limit 3
    import autorunner
    reason = autorunner.guardrail("KLC-G2", "build", 0, cap=99)
    assert reason and "budget" in reason.lower(), reason


def test_guardrail_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-G3", "build:work", "S")
    import autorunner
    reason = autorunner.guardrail("KLC-G3", "build", 5, cap=5)
    assert reason and "cap" in reason.lower(), reason


def test_guardrail_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-G4", "build:work", "S")
    import autorunner
    assert autorunner.guardrail("KLC-G4", "build", 0, cap=20) is None


def test_cap_loader_separate_from_budget(tmp_path, monkeypatch):
    """audit fix #3: the consecutive-auto cap must NOT be a budget._load_limits() key."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    import autorunner, budget
    assert "consecutive_auto_transitions" not in budget._load_limits()
    # env override honoured
    monkeypatch.setenv("KLC_AUTORUN_CAP", "7")
    assert autorunner._cap() == 7


# ===========================================================================
# step-2: dispatch routing (AC-1)
# ===========================================================================

def test_run_dispatches_work_state(tmp_path, monkeypatch):
    """Build routes to the orchestrator (out under build/); others to run_agent
    with track=. ZERO real agent calls."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-D1", "build:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner
    calls: list = []
    fake = _make_green_dispatch(td, calls)
    res = autorunner.run("KLC-D1", dispatch=fake, cap=20)
    phases_seen = {c["phase"] for c in calls}
    assert "build" in phases_seen and "review" in phases_seen, calls
    build_call = next(c for c in calls if c["phase"] == "build")
    review_call = next(c for c in calls if c["phase"] == "review")
    assert "/build/" in build_call["out"], build_call  # orchestrator report path
    assert review_call["track"] == "S", review_call
    assert res.paused_at == "integrate"


def test_dispatch_uses_rendered_card_not_generic_prompt(tmp_path, monkeypatch):
    """P1-A: a non-build phase is dispatched with the RENDERED per-ticket card
    (.klc/tickets/<KEY>/<phase>/_prompt.md), NOT the generic core/agents role
    prompt (which is full of <KEY> placeholders and generic input descriptions)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-D2", "review:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner
    calls: list = []
    autorunner.run("KLC-D2", dispatch=_make_green_dispatch(td, calls), cap=20)
    review_call = next(c for c in calls if c["phase"] == "review")
    prompt = review_call["prompt"].replace("\\", "/")
    assert prompt.endswith("/review/_prompt.md"), prompt
    assert "core/agents" not in prompt, prompt
    # and the card was actually rendered on disk with the concrete key
    card = td / "review" / "_prompt.md"
    assert card.exists()
    assert "KLC-D2" in card.read_text(encoding="utf-8")


def test_missing_declared_output_fails_closed(tmp_path, monkeypatch):
    """P1-B (via the track-aware gate, not a duplicated pre-check): if a dispatch
    does not produce the artifacts the phase's can_complete requires, `ack --auto`
    returns rc 1 and the loop pauses fail-closed — with the gate's CAUSAL reason
    (the missing artifact), not the generic last-line abort hint."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-D3", "review:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    # dispatch returns 0 but writes NOTHING → review-report.md never produced.
    res = autorunner.run("KLC-D3", dispatch=lambda *a, **k: 0, cap=20)
    assert res.paused_at == "review"
    # FIX-2: the causal line ("Missing review-report.md") must be surfaced, not
    # just the trailing "(or `klc abort ...` to cancel)." hint.
    assert res.reason and "review-report.md" in res.reason, res.reason
    assert lifecycle.current_state("KLC-D3") == "review:work"  # NOT advanced
    log = (td / "run-log.md").read_text(encoding="utf-8")
    assert "review-report.md" in log, log


def _make_xs_ticket(tmp_path: Path, ticket: str) -> Path:
    """A valid XS ticket at discovery-lite:work whose ONLY discovery-lite
    requirement is spec.md (per can_complete_discovery_lite), even though
    phases.yml lists test-plan.md + impl-plan.md as discovery-lite outputs."""
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "discovery-lite:work",
        "track": "XS", "route_confidence": "high", "affected_modules": ["m"],
        "layer": "code",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "budgets": {}, "risk_tags": [], "phase_history": [],
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(
        "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo an XS thing.\n## Acceptance Criteria\n- [ ] AC-1: does it.\n"
        "## Affected\nm: core/x.py\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 0\nrisk: 0\nmanual: 0\ntotal: 1\n"
        .format(t=ticket), encoding="utf-8")
    _modules_json(tmp_path)
    return td


def test_xs_discovery_lite_not_wrongly_paused(tmp_path, monkeypatch):
    """FIX-1: an XS discovery-lite dispatch that produces only spec.md (all XS
    requires) must NOT be wrongly paused for a 'missing' test-plan.md/impl-plan.md
    (phases.yml lists those, but the XS gate does not require them). The loop must
    reach discovery-lite:ack-needed and pause at the DECISION gate instead."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_xs_ticket(tmp_path, "KLC-XS1")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    # no-op dispatch: spec.md already present (as a discovery-lite agent would
    # have produced); test-plan.md / impl-plan.md deliberately absent.
    res = autorunner.run("KLC-XS1", dispatch=lambda *a, **k: 0, cap=20)
    # Must have advanced past :work to the decision gate — NOT paused at :work
    # with a missing-output reason.
    assert lifecycle.current_state("KLC-XS1") == "discovery-lite:ack-needed", \
        f"XS discovery-lite wrongly blocked: {res.reason}"
    assert res.paused_at == "discovery-lite"
    assert res.reason and "decision" in res.reason.lower(), res.reason
    assert "test-plan.md" not in (res.reason or ""), res.reason


# ===========================================================================
# step-3: run loop (AC-2, AC-3, AC-5, AC-7)
# ===========================================================================

def test_run_auto_acks_clean_conditional(tmp_path, monkeypatch):
    """AC-2: a clean conditional gate auto-acks and lifecycle advances."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-A1", "build:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    calls: list = []
    autorunner.run("KLC-A1", dispatch=_make_green_dispatch(td, calls), cap=20)
    # build (conditional) auto-acked → walked past review → halted at integrate
    assert lifecycle.current_state("KLC-A1") == "integrate:work"


def test_run_pauses_on_decision_gate(tmp_path, monkeypatch):
    """AC-3: a decision gate pauses even with clean signals; phase UNCHANGED."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-A2", "design:ack-needed", "M")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    res = autorunner.run("KLC-A2", dispatch=lambda *a, **k: 0, cap=20)
    assert res.paused_at == "design"
    assert res.reason and "decision" in res.reason.lower(), res.reason
    assert lifecycle.current_state("KLC-A2") == "design:ack-needed"


def test_run_already_at_decision(tmp_path, monkeypatch):
    """A ticket already at a decision gate → immediate pause, no dispatch."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-A3", "design:ack-needed", "M")
    _patch_clean_signals(monkeypatch)
    import autorunner
    calls: list = []
    res = autorunner.run("KLC-A3", dispatch=lambda *a, **k: (calls.append(a) or 0), cap=20)
    assert res.paused_at == "design"
    assert calls == [], "no dispatch should occur when starting at a decision gate"


def test_run_ml_design_decision_simulation(tmp_path, monkeypatch):
    """AC-5a: an M fixture at design:work halts at the design decision gate."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-A4", "design:work", "M")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    calls: list = []
    res = autorunner.run("KLC-A4", dispatch=_make_green_dispatch(td, calls), cap=20)
    assert res.paused_at == "design"
    assert lifecycle.current_state("KLC-A4") == "design:ack-needed"
    assert any(c["phase"] == "design" for c in calls)


def test_run_clean_s_ticket_simulation(tmp_path, monkeypatch):
    """AC-5b: an S fixture walks build→review then halts at the integrate guardrail."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-A5", "build:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    res = autorunner.run("KLC-A5", dispatch=_make_green_dispatch(td, []), cap=20)
    assert res.transitions == ["build", "review"], res.transitions
    assert res.paused_at == "integrate"
    assert res.reason and ("integrate" in res.reason.lower() or "outward" in res.reason.lower())
    assert lifecycle.current_state("KLC-A5") == "integrate:work"


def test_run_refuses_feature_on(tmp_path, monkeypatch):
    """AC-7: feature-ON → refuse, no transition."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-F1", "build:work", "S")
    import autorunner, state_feature, lifecycle
    monkeypatch.setattr(state_feature, "enabled", lambda: True)
    called = []
    res = autorunner.run("KLC-F1", dispatch=lambda *a, **k: (called.append(a) or 0), cap=20)
    assert res.reason and "refus" in res.reason.lower()
    assert called == []
    assert lifecycle.current_state("KLC-F1") == "build:work"  # unchanged


# ===========================================================================
# edge cases + safety invariant
# ===========================================================================

def test_run_dispatch_failure_pauses(tmp_path, monkeypatch):
    """A dispatched agent returning non-zero pauses at :work; no advance."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-E1", "review:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    res = autorunner.run("KLC-E1", dispatch=lambda *a, **k: 1, cap=20)
    assert res.paused_at == "review"
    assert res.reason and "dispatch" in res.reason.lower()
    assert lifecycle.current_state("KLC-E1") == "review:work"


def test_run_cap_mid_run(tmp_path, monkeypatch):
    """Consecutive-auto cap reached mid-run → pause with the cap guardrail."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-E2", "build:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner
    res = autorunner.run("KLC-E2", dispatch=_make_green_dispatch(td, []), cap=1)
    # build auto-acks (n_auto→1); then cap fires before review acks
    assert res.reason and "cap" in res.reason.lower()
    assert res.paused_at == "review"


def test_run_writes_run_log(tmp_path, monkeypatch):
    """AC-6: the run log records transitions and the pause reason."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-E3", "build:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner
    autorunner.run("KLC-E3", dispatch=_make_green_dispatch(td, []), cap=20)
    log = (td / "run-log.md").read_text(encoding="utf-8")
    assert "build" in log and "review" in log
    assert "integrate" in log.lower()
    assert "paused" in log.lower() or "guardrail" in log.lower()


def test_run_never_merges_or_pushes(tmp_path, monkeypatch):
    """SAFETY INVARIANT: driving the full S simulation issues ZERO git merge /
    git push, and pauses at integrate."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-S1", "build:work", "S")
    _patch_clean_signals(monkeypatch)

    import subprocess
    recorded: list = []
    real_run = subprocess.run
    real_call = subprocess.call

    def rec_run(cmd, *a, **k):
        recorded.append(list(cmd) if isinstance(cmd, (list, tuple)) else [cmd])
        return real_run(cmd, *a, **k)

    def rec_call(cmd, *a, **k):
        recorded.append(list(cmd) if isinstance(cmd, (list, tuple)) else [cmd])
        return real_call(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", rec_run)
    monkeypatch.setattr(subprocess, "call", rec_call)

    import autorunner
    res = autorunner.run("KLC-S1", dispatch=_make_green_dispatch(td, []), cap=20)

    forbidden = [
        c for c in recorded
        if len(c) >= 2 and str(c[0]).endswith("git") and c[1] in ("merge", "push")
    ]
    assert forbidden == [], f"runner must never merge/push, saw: {forbidden}"
    assert res.paused_at == "integrate"


# ===========================================================================
# step-5: klc run verb
# ===========================================================================

def test_run_registered(tmp_path, monkeypatch):
    """`klc run <KEY>` routes to the runner, accepts --cap, and exits 2 on pause."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-R1", "build:work", "S")
    _patch_clean_signals(monkeypatch)
    import run as run_verb
    # patch autorunner.run's dispatch by patching the module default via verb path:
    import autorunner
    monkeypatch.setattr(autorunner, "run",
                        lambda t, **k: autorunner.RunResult(["build"], "integrate", "integrate guardrail"))
    rc = run_verb.run(["KLC-R1", "--cap", "5"])
    assert rc == 2, "a paused run exits 2"


def test_run_verb_refusal_rc1(tmp_path, monkeypatch):
    """`klc run` on a feature-ON project refuses and exits 1 (distinct from done=0)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-R2", "build:work", "S")
    import run as run_verb
    import state_feature
    monkeypatch.setattr(state_feature, "enabled", lambda: True)
    rc = run_verb.run(["KLC-R2"])
    assert rc == 1, "a refusal exits 1"


def test_run_verb_done_rc0(tmp_path, monkeypatch):
    """`klc run` exits 0 when the loop reaches a terminal/clean stop (archived)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-R3", "build:work", "S")
    import run as run_verb
    import autorunner
    monkeypatch.setattr(autorunner, "run",
                        lambda t, **k: autorunner.RunResult(["build", "review"], None, None))
    rc = run_verb.run(["KLC-R3"])
    assert rc == 0, "a clean/archived run exits 0"


def test_run_badkey_rc1_no_dir(tmp_path, monkeypatch):
    """P2: `klc run <BADKEY>` → rc 1, friendly, and NO .klc/tickets/<BADKEY>/
    directory is created (no _log/state mutation before validation)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    import run as run_verb
    rc = run_verb.run(["KLC-NOPE"])
    assert rc == 1, "unknown ticket exits 1"
    assert not (tmp_path / ".klc" / "tickets" / "KLC-NOPE").exists(), \
        "must not create a bogus ticket dir for an unknown key"


def test_run_badkey_no_traceback(tmp_path, monkeypatch):
    """autorunner.run on an unknown key returns a refusal RunResult (no crash)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    import autorunner
    res = autorunner.run("KLC-GHOST")
    assert res.paused_at is None and res.reason and "unknown" in res.reason.lower()
    assert not (tmp_path / ".klc" / "tickets" / "KLC-GHOST").exists()


def test_corrupt_meta_logged_pause(tmp_path, monkeypatch):
    """Exception guard: a corrupt meta.json mid-run becomes a LOGGED pause
    (fail-closed), not a traceback."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = tmp_path / ".klc" / "tickets" / "KLC-CM1"
    td.mkdir(parents=True)
    (td / "meta.json").write_text("{ this is not valid json", encoding="utf-8")
    import autorunner
    res = autorunner.run("KLC-CM1", dispatch=lambda *a, **k: 0, cap=20)
    assert res.paused_at is not None, "a mid-run error must pause (rc 2), not crash"
    log = (td / "run-log.md").read_text(encoding="utf-8")
    assert "error" in log.lower() or "fail-closed" in log.lower()


def test_refusal_feature_on_is_logged(tmp_path, monkeypatch):
    """LOW: the feature-on refusal is recorded in the run log."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-RL1", "build:work", "S")
    import autorunner, state_feature
    monkeypatch.setattr(state_feature, "enabled", lambda: True)
    autorunner.run("KLC-RL1", dispatch=lambda *a, **k: 0, cap=20)
    log = (td / "run-log.md").read_text(encoding="utf-8")
    assert "refus" in log.lower() and "feature" in log.lower()


def test_ack_error_reason_includes_detail(tmp_path, monkeypatch):
    """LOW: a non-2 non-0 ack rc surfaces ack's stderr detail into the pause
    reason (not a bare 'ack --auto error (rc=N)')."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    td = _make_ticket(tmp_path, "KLC-AE1", "build:work", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner
    # dispatch writes build-log so outputs pass, but make ack --auto return rc 1
    # with a recognisable stderr line.
    def bad_ack(argv):
        sys.stderr.write("klc ack: scope expansion detected — unplanned modules\n")
        return 1
    monkeypatch.setattr(autorunner, "_ack_cmd", type("M", (), {"run": staticmethod(bad_ack)}))
    res = autorunner.run("KLC-AE1", dispatch=_make_green_dispatch(td, []), cap=20)
    assert res.reason and "rc=1" in res.reason
    assert "scope expansion" in res.reason, res.reason


def test_run_ack_state_advances(tmp_path, monkeypatch):
    """A lingering :ack state is advanced by the loop (advance_to_next), then the
    next state's guardrail/gate applies. Exercises the else branch of the loop."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    _make_ticket(tmp_path, "KLC-K1", "review:ack", "S")
    _patch_clean_signals(monkeypatch)
    import autorunner, lifecycle
    res = autorunner.run("KLC-K1", dispatch=lambda *a, **k: 0, cap=20)
    # review:ack → advance_to_next → integrate:work → integrate guardrail pause
    assert res.paused_at == "integrate"
    assert lifecycle.current_state("KLC-K1") == "integrate:work"
