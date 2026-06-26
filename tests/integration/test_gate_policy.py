"""Tests for KLC-045: gate-policy layer.

step-1: Pick.gate field + phases.yml annotations
step-2: evaluate() predicate (fail-closed)
step-3: collect_signals() from real skill APIs
step-4: klc ack --auto applies gate-policy
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import pytest

# ---------------------------------------------------------------------------
# step-1: Pick.gate field + phases.yml annotations
# ---------------------------------------------------------------------------

def test_pick_gate_field_parsed():
    """Pick dataclass has a 'gate' field; _build_pick reads it from YAML."""
    from core.skills import phases as ph

    # Use the real loader on a minimal in-memory YAML snippet via a temp file.
    yml = """
phases:
  - id: test-phase
    tracks: [M]
    work:
      prompt: ""
    ack:
      pick_required: true
      picks:
        - id: 1
          label: approve
          goto: "next"
          gate: conditional
        - id: 2
          label: needs-rework
          goto: "test-phase:work"
          gate: decision
    inputs: []
    outputs: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(yml)
        tmp = Path(f.name)

    try:
        raw = ph._load_raw(tmp)
        phase_data = raw["phases"][0]
        picks = [ph._build_pick(p, "test-phase") for p in phase_data["ack"]["picks"]]
        assert picks[0].gate == "conditional"
        assert picks[1].gate == "decision"
    finally:
        tmp.unlink(missing_ok=True)


def test_pick_gate_unknown_raises():
    """_build_pick raises ValueError for an unknown gate value (fail-closed)."""
    from core.skills import phases as ph

    bad = {"id": 1, "label": "x", "goto": "next", "gate": "maybe"}
    with pytest.raises(ValueError, match="bad gate"):
        ph._build_pick(bad, "test-phase")


def test_every_pick_has_gate():
    """Every pick in the REAL phases.yml has a 'gate' attribute set."""
    from core.skills.phases import load_phases
    ph = load_phases(force=True)
    missing = []
    for phase in ph.ordered:
        for pick in phase.picks:
            if not hasattr(pick, "gate") or pick.gate not in ("auto", "conditional", "decision"):
                missing.append(f"{phase.id}:pick-{pick.id} (gate={getattr(pick, 'gate', '<missing>')})")
    assert not missing, f"Picks missing valid gate annotation: {missing}"


# ---------------------------------------------------------------------------
# step-2: evaluate() predicate (fail-closed)
# ---------------------------------------------------------------------------

_CLEAN_SIGNALS = {
    "advisory": "",
    "scope_expansion": False,
    "sentinels": False,
    "mutation": False,
    "budget_overrun": False,
    "verdict": "APPROVED",
    "route_confidence": "high",
}


def test_evaluate_auto_always_proceeds():
    from core.skills.gate_policy import evaluate
    d = evaluate("auto", {})
    assert d.proceed is True
    assert d.reasons == []


def test_evaluate_decision_always_pauses():
    from core.skills.gate_policy import evaluate
    d = evaluate("decision", _CLEAN_SIGNALS)
    assert d.proceed is False
    assert any("human" in r.lower() or "decision" in r.lower() for r in d.reasons)


def test_evaluate_conditional_clean_proceeds():
    from core.skills.gate_policy import evaluate
    d = evaluate("conditional", _CLEAN_SIGNALS)
    assert d.proceed is True
    assert d.reasons == []


def test_evaluate_conditional_dirty_pauses():
    from core.skills.gate_policy import evaluate
    dirty = {**_CLEAN_SIGNALS, "scope_expansion": True, "verdict": "CHANGES_REQUESTED"}
    d = evaluate("conditional", dirty)
    assert d.proceed is False
    assert "scope_expansion" in d.reasons or any("scope_expansion" in r for r in d.reasons)
    assert "verdict" in d.reasons or any("verdict" in r for r in d.reasons)


def test_evaluate_missing_signal_is_dirty():
    """A missing key in signals is treated as dirty (fail-closed), not clean."""
    from core.skills.gate_policy import evaluate

    # Drop route_confidence entirely — must NOT proceed
    no_rc = {k: v for k, v in _CLEAN_SIGNALS.items() if k != "route_confidence"}
    d = evaluate("conditional", no_rc)
    assert d.proceed is False
    assert any("route_confidence" in r for r in d.reasons), (
        f"expected 'route_confidence' in reasons, got: {d.reasons}"
    )

    # Drop verdict entirely — must NOT proceed
    no_verdict = {k: v for k, v in _CLEAN_SIGNALS.items() if k != "verdict"}
    d2 = evaluate("conditional", no_verdict)
    assert d2.proceed is False
    assert any("verdict" in r for r in d2.reasons)


# ---------------------------------------------------------------------------
# step-3: collect_signals() from real skill APIs
# ---------------------------------------------------------------------------

def _make_clean_ticket(tmp_path: Path, ticket: str) -> Path:
    """Minimal ticket with clean state: no scope expansion, no budget overrun, clean review."""
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "review:ack-needed",
        "track": "S",
        "route_confidence": "high",
        "affected_modules": ["test_module"],
        "layer": "code",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "budgets": {"mutation_fix_attempts": 0},
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(
        "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
        "## Affected\ntest_module: core/test.py, src=core/test.py:1\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
        .format(t=ticket),
        encoding="utf-8",
    )
    # Clean review-report with APPROVED verdict
    (td / "review-report.md").write_text(
        "# Review report\n\n## Findings\n\nNone.\n\n## Verdict\n\nAPPROVED\n",
        encoding="utf-8",
    )
    return td


def _make_dirty_ticket(tmp_path: Path, ticket: str) -> Path:
    """Ticket with scope expansion and budget-at-limit."""
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "review:ack-needed",
        "track": "S",
        "route_confidence": "low",
        "affected_modules": ["module_A"],
        "layer": "code",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "budgets": {"mutation_fix_attempts": 3},
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(
        "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
        "## Affected\nmodule_A: core/test.py, src=core/test.py:1\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
        .format(t=ticket),
        encoding="utf-8",
    )
    # review-report with CHANGES REQUESTED
    (td / "review-report.md").write_text(
        "# Review report\n\n## Findings\n\n- Issue found.\n\n## Verdict\n\nCHANGES REQUESTED\n",
        encoding="utf-8",
    )
    return td


def _make_modules_json(tmp_path: Path, modules: dict) -> None:
    idx = tmp_path / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")


def test_collect_signals_clean(tmp_path, monkeypatch):
    """A clean fixture ticket yields all seven signals clean."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-CS01"
    _make_clean_ticket(tmp_path, ticket)
    # modules.json: ticket's module matches
    _make_modules_json(tmp_path, {
        "test_module": {"src": ["core/test.py"], "tests": [], "phase": "stable"}
    })

    from core.skills import gate_policy
    sig = gate_policy.collect_signals(ticket, "review")

    assert "advisory" in sig
    assert "scope_expansion" in sig
    assert "sentinels" in sig
    assert "mutation" in sig
    assert "budget_overrun" in sig
    assert "verdict" in sig
    assert "route_confidence" in sig

    # verdict should be clean (APPROVED)
    assert sig["verdict"] in ("approve", "APPROVED", "PASS", "clean"), sig["verdict"]
    # route_confidence: "high" → clean
    assert sig["route_confidence"] == "high"
    # mutation: counter=0, limit=3 → not at limit → False
    assert sig["mutation"] is False
    # budget_overrun: counter=0 everywhere → False
    assert sig["budget_overrun"] is False


def test_collect_signals_dirty(tmp_path, monkeypatch):
    """A dirty fixture yields dirty signals for budget and verdict."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-DS01"
    _make_dirty_ticket(tmp_path, ticket)
    _make_modules_json(tmp_path, {
        "module_A": {"src": ["core/test.py"], "tests": [], "phase": "stable"}
    })

    from core.skills import gate_policy
    sig = gate_policy.collect_signals(ticket, "review")

    # mutation at limit (3 >= 3) → True (dirty)
    assert sig["mutation"] is True, f"expected mutation dirty, got: {sig['mutation']}"
    # verdict: CHANGES REQUESTED → not clean
    assert sig["verdict"] not in ("approve", "APPROVED", "PASS", "clean"), (
        f"expected verdict dirty, got: {sig['verdict']}"
    )
    # route_confidence: "low"
    assert sig["route_confidence"] == "low"


def test_collect_signals_no_review_report(tmp_path, monkeypatch):
    """Missing review-report.md yields a dirty (non-clean) verdict."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-NR01"
    td = _make_clean_ticket(tmp_path, ticket)
    (td / "review-report.md").unlink()
    _make_modules_json(tmp_path, {
        "test_module": {"src": ["core/test.py"], "tests": [], "phase": "stable"}
    })

    from core.skills import gate_policy
    sig = gate_policy.collect_signals(ticket, "review")
    assert sig["verdict"] not in ("approve", "APPROVED", "PASS", "clean"), (
        f"expected dirty verdict when review-report.md missing, got: {sig['verdict']}"
    )


# ---------------------------------------------------------------------------
# step-4: klc ack --auto applies gate-policy
# ---------------------------------------------------------------------------

_PHASES_CACHE_ATTR = "_CACHE"  # phases.py module-level cache


def _flush_phases_cache():
    import importlib
    import core.skills.phases as ph_mod
    ph_mod._CACHE = None


def _make_build_ticket(tmp_path: Path, ticket: str, route_confidence: str = "high") -> Path:
    """Ticket in build:ack-needed — single conditional forward pick."""
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "build:ack-needed",
        "track": "S",
        "route_confidence": route_confidence,
        "affected_modules": ["test_module"],
        "layer": "code",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "budgets": {"mutation_fix_attempts": 0},
        "phase_history": [],
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(
        "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
        "## Affected\ntest_module: core/test.py, src=core/test.py:1\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
        .format(t=ticket),
        encoding="utf-8",
    )
    (td / "impl-plan.md").write_text(
        "## step-1 — do the thing\n- **Goal:** implement\n- RED: not applicable\n"
        "- **Interfaces:** `def f() -> None`\n- **Expected:** f runs\n"
        "- **VERIFY:** pytest\n- **COMMIT:** KLC-X step-1: do the thing\n"
        "- **Affected:** src/x.py\n- **Code sketch:**\n```python\npass\n```\n",
        encoding="utf-8",
    )
    (td / "build-log.md").write_text(
        "## Evidence\n\n```\n$ pytest\n1 passed\n```\n",
        encoding="utf-8",
    )
    # review-report with APPROVED
    (td / "review-report.md").write_text(
        "# Review report\n\n## Verdict\n\nAPPROVED\n",
        encoding="utf-8",
    )
    return td


def _make_design_ticket(tmp_path: Path, ticket: str) -> Path:
    """Ticket in design:ack-needed — decision picks (option-A/B/C)."""
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "design:ack-needed",
        "track": "M",
        "route_confidence": "high",
        "affected_modules": ["test_module"],
        "layer": "code",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "budgets": {},
        "phase_history": [],
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(
        "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo M thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
        "## Affected\ntest_module: core/test.py, src=core/test.py:1\n"
        "## Estimate\ncomplexity: 2\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 4\n"
        .format(t=ticket),
        encoding="utf-8",
    )
    design_dir = td / "design"
    design_dir.mkdir()
    (design_dir / "options.md").write_text(
        "# Design options\n\n## Option A\nFast.\n\nADR_NEEDED=no REASON=\"minimal\"\n",
        encoding="utf-8",
    )
    (td / "impl-plan.md").write_text(
        "## step-1 — do the thing\n- **Goal:** implement\n- RED: not applicable\n"
        "- **Interfaces:** `def f() -> None`\n- **Expected:** f runs\n"
        "- **VERIFY:** pytest\n- **COMMIT:** KLC-X step-1: do the thing\n"
        "- **Affected:** src/x.py\n- **Code sketch:**\n```python\npass\n```\n",
        encoding="utf-8",
    )
    return td


_CLEAN_SIG = {
    "advisory": "",
    "scope_expansion": False,
    "sentinels": False,
    "mutation": False,
    "budget_overrun": False,
    "verdict": "APPROVED",
    "route_confidence": "high",
}

_SCOPE_DIRTY_SIG = {
    **_CLEAN_SIG,
    "scope_expansion": True,
}

_LOW_RC_SIG = {
    **_CLEAN_SIG,
    "route_confidence": "low",
}


_CLEAN_SIG = {
    "advisory": "",
    "scope_expansion": False,
    "sentinels": False,
    "mutation": False,
    "budget_overrun": False,
    "verdict": "APPROVED",
    "route_confidence": "high",
}

_SCOPE_DIRTY_SIG = {
    **_CLEAN_SIG,
    "scope_expansion": True,
}

_LOW_RC_SIG = {
    **_CLEAN_SIG,
    "route_confidence": "low",
}


def _patch_collect(monkeypatch, ack_mod, sig_dict: dict):
    """Patch gate_policy.collect_signals as seen by ack.py (via its _gp reference)."""
    monkeypatch.setattr(ack_mod._gp, "collect_signals", lambda t, p: dict(sig_dict))


def test_ack_auto_proceeds_clean(tmp_path, monkeypatch):
    """--auto on a conditional pick with clean signals auto-acks and transitions."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    ticket = "KLC-AA01"
    _make_build_ticket(tmp_path, ticket)

    import ack as ack_mod
    _patch_collect(monkeypatch, ack_mod, _CLEAN_SIG)

    rc = ack_mod.run([ticket, "--auto"])
    assert rc == 0, f"expected exit 0 for clean conditional auto-ack, got {rc}"

    from core.skills import lifecycle
    state = lifecycle.current_state(ticket)
    assert state != "build:ack-needed", (
        f"expected phase to advance past build:ack-needed, got: {state}"
    )


def test_ack_auto_refuses_risky(tmp_path, monkeypatch, capsys):
    """--auto refuses when scope_expansion is dirty; names the reason; phase unchanged."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    ticket = "KLC-AA02"
    _make_build_ticket(tmp_path, ticket)

    import ack as ack_mod
    _patch_collect(monkeypatch, ack_mod, _SCOPE_DIRTY_SIG)

    rc = ack_mod.run([ticket, "--auto"])
    assert rc != 0, "expected non-zero when scope expansion present"

    from core.skills import lifecycle
    state = lifecycle.current_state(ticket)
    assert state == "build:ack-needed", f"expected phase unchanged, got: {state}"


def test_ack_auto_refuses_low_route_confidence(tmp_path, monkeypatch, capsys):
    """--auto refuses when route_confidence is 'low'; phase unchanged."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    ticket = "KLC-AA03"
    _make_build_ticket(tmp_path, ticket, route_confidence="low")

    import ack as ack_mod
    _patch_collect(monkeypatch, ack_mod, _LOW_RC_SIG)

    rc = ack_mod.run([ticket, "--auto"])
    assert rc != 0, "expected non-zero when route_confidence is low"

    from core.skills import lifecycle
    state = lifecycle.current_state(ticket)
    assert state == "build:ack-needed", f"expected phase unchanged, got: {state}"


def test_decision_never_auto(tmp_path, monkeypatch, capsys):
    """A decision pick never auto-acks even with perfectly clean signals."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    ticket = "KLC-DA01"
    _make_design_ticket(tmp_path, ticket)

    import ack as ack_mod
    _patch_collect(monkeypatch, ack_mod, _CLEAN_SIG)

    rc = ack_mod.run([ticket, "--auto"])
    assert rc != 0, "expected non-zero for decision gate even with clean signals"

    from core.skills import lifecycle
    state = lifecycle.current_state(ticket)
    assert state == "design:ack-needed", f"expected phase unchanged, got: {state}"


def test_ack_no_auto_unchanged(tmp_path, monkeypatch):
    """Plain 'klc ack' without --auto behaves exactly as today (no policy consulted)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    ticket = "KLC-NA01"
    _make_build_ticket(tmp_path, ticket)

    import ack as ack_mod
    # Plain ack with pick=1 (only pick for build) should work as before
    rc = ack_mod.run([ticket, "--pick", "1"])
    assert rc == 0, f"expected exit 0 for plain ack --pick 1, got {rc}"
