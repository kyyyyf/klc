"""KLC-081 feature-OFF unit coverage for the `rework_count` increment.

`meta.rework_count` ({phase: count}) is initialized to `{}` at intake and read
by metrics.py (rework_mean / cheap_escape_rate) and the `learn` conditional gate.
Before KLC-081 nothing incremented it, so those consumers never saw rework. These
tests prove the three backward/rework transitions now bump it — and, critically,
that the happy (no-rework) path leaves it `{}`.

Transition tests drive the real `scripts/klc` CLI via subprocess (feature-OFF: no
`.klc` git worktree ⇒ state_tx is a pure local write). The metrics-rollup and
learn-gate tests run in-process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
KLC = FW_ROOT / "scripts" / "klc"
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

import phases as _ph  # noqa: E402


def _env(root: Path) -> dict[str, str]:
    e = {**os.environ, "PROJECT_ROOT": str(root)}
    e.pop("KLC_TICKETS_DIR", None)
    return e


def _bootstrap(root: Path, ticket: str, *, phase: str, track: str = "M",
               rework_count: dict | None = None,
               artefacts: dict | None = None) -> Path:
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase,
        "phase_history": [{"phase": phase, "started_at": "2026-01-01T00:00:00Z"}],
        "track": track, "route_hint": track, "affected_modules": [],
        "budgets": {"mutation_fix_attempts": 3},
        "estimate": None, "jira_url": None, "created": "2026-01-01T00:00:00Z",
        "rework_count": {} if rework_count is None else rework_count,
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for rel, text in (artefacts or {}).items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tdir / "meta.json"


def _run(args: list[str], root: Path):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=_env(root))


# --- the three backward/rework transitions bump rework_count -----------------

def test_needs_rework_ack_pick_bumps_reentered_phase(tmp_path):
    """A request-changes/regression ack pick that sends work BACK into an earlier
    phase's :work bumps rework_count for that re-entered phase (observe
    "regression" → build:work ⇒ rework_count == {build: 1})."""
    meta_p = _bootstrap(tmp_path, "K81-ACK", phase="observe:ack-needed")
    r = _run(["ack", "K81-ACK", "--pick", "2"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "build:work"
    assert m["rework_count"] == {"build": 1}, m["rework_count"]


def test_backward_jump_bumps_target_phase(tmp_path):
    """A backward `klc jump` re-enters an earlier phase → rework of the target."""
    meta_p = _bootstrap(tmp_path, "K81-JMP", phase="review:ack")
    r = _run(["jump", "build", "K81-JMP", "--yes"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "build:work"
    assert m["rework_count"] == {"build": 1}, m["rework_count"]


def test_abort_bumps_scrapped_current_phase(tmp_path):
    """`klc abort` scraps the current :work (redone later) → rework of cur_pid."""
    meta_p = _bootstrap(tmp_path, "K81-ABT", phase="build:work")
    r = _run(["abort", "K81-ABT"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "design:ack", "abort steps back to the previous :ack"
    assert m["rework_count"] == {"build": 1}, m["rework_count"]


def test_rework_count_accumulates_and_preserves_map(tmp_path):
    """A bump adds to an existing map without clobbering other phases' counts."""
    meta_p = _bootstrap(tmp_path, "K81-ACC", phase="build:work",
                        rework_count={"design": 2, "build": 1})
    assert _run(["abort", "K81-ACC"], tmp_path).returncode == 0
    m = json.loads(meta_p.read_text())
    assert m["rework_count"] == {"design": 2, "build": 2}, m["rework_count"]


# --- happy path: a forward transition is a byte-clean no-op ------------------

def test_forward_ack_leaves_rework_empty(tmp_path):
    """A forward ack pick (goto next) never touches rework_count — it stays {}."""
    meta_p = _bootstrap(tmp_path, "K81-FWD", phase="observe:ack-needed")
    r = _run(["ack", "K81-FWD", "--pick", "1"], tmp_path)   # "clean" → next
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] != "build:work", "pick 1 (clean) must advance forward"
    assert m["rework_count"] == {}, m["rework_count"]


def test_forward_next_leaves_rework_empty(tmp_path):
    """`klc next` (forward advance) never touches rework_count."""
    meta_p = _bootstrap(tmp_path, "K81-NXT", phase="design:ack")
    r = _run(["next", "K81-NXT"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["rework_count"] == {}, m["rework_count"]


def test_forward_jump_is_not_rework(tmp_path):
    """A forward `klc jump` (to a later phase, nothing to supersede) is a route
    move, not rework — rework_count stays {}."""
    meta_p = _bootstrap(tmp_path, "K81-FJ", phase="design:ack")
    r = _run(["jump", "review", "K81-FJ", "--yes"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "review:work"
    assert m["rework_count"] == {}, m["rework_count"]


# --- semantic gate: same-phase rework counts, learn self-loop does not -------

def test_same_phase_needs_rework_ack_bumps(tmp_path):
    """The MOST COMMON rework: a same-phase `needs-rework` ack pick
    (design:ack-needed pick 4 → design:work) MUST count rework of that phase.
    Locks the semantic gate so a naive `<`-direction "fix" (which would silently
    stop counting same-phase needs-rework) is caught."""
    meta_p = _bootstrap(tmp_path, "K81-SPR", phase="design:ack-needed")
    r = _run(["ack", "K81-SPR", "--pick", "4"], tmp_path)   # "needs-rework"
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "design:work"
    assert m["rework_count"] == {"design": 1}, m["rework_count"]


def test_learn_extract_to_claudemd_self_loop_does_not_bump(tmp_path):
    """The learn `extract-to-claudemd` self-loop (learn:ack-needed pick 2 →
    learn:work) is a legitimate second pass, NOT rework — rework_count stays {}.
    It is same-phase goto:work exactly like `needs-rework`, so only the
    rework-label gate (not raw direction) can exclude it."""
    meta_p = _bootstrap(tmp_path, "K81-LEX", phase="learn:ack-needed")
    r = _run(["ack", "K81-LEX", "--pick", "2"], tmp_path)   # "extract-to-claudemd"
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "learn:work"
    assert m["rework_count"] == {}, m["rework_count"]


def test_manual_failed_ack_bumps_build(tmp_path):
    """manual "failed" → build:work (a cross-phase backward bounce) counts as
    rework of the re-entered build phase."""
    meta_p = _bootstrap(tmp_path, "K81-MF", phase="manual:ack-needed")
    r = _run(["ack", "K81-MF", "--pick", "2"], tmp_path)   # "failed"
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "build:work"
    assert m["rework_count"] == {"build": 1}, m["rework_count"]


def test_sequential_live_backward_transitions_accumulate(tmp_path):
    """LOW-4: multiple LIVE backward transitions on one ticket accumulate.
    build is counted twice (ack "failed" → build, then abort build) and a later
    backward jump adds a DISTINCT acceptance-test-plan key — proving live
    accumulation across keys, not just a seeded prior."""
    meta_p = _bootstrap(tmp_path, "K81-SEQ", phase="manual:ack-needed")
    # 1) manual "failed" → build:work
    assert _run(["ack", "K81-SEQ", "--pick", "2"], tmp_path).returncode == 0
    assert json.loads(meta_p.read_text())["rework_count"] == {"build": 1}
    # 2) abort build:work → design:ack (bumps build again)
    assert _run(["abort", "K81-SEQ"], tmp_path).returncode == 0
    assert json.loads(meta_p.read_text())["rework_count"] == {"build": 2}
    # 3) backward jump design:ack → acceptance-test-plan:work (distinct key)
    assert _run(["jump", "acceptance-test-plan", "K81-SEQ", "--yes"],
                tmp_path).returncode == 0
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "acceptance-test-plan:work"
    assert m["rework_count"] == {"build": 2, "acceptance-test-plan": 1}, \
        m["rework_count"]


def test_bump_tolerates_corrupt_prior_value(tmp_path):
    """LOW-2: a truthy non-numeric prior count must NOT crash the transition;
    the coercion falls back to 0, so the bump yields 1."""
    meta_p = _bootstrap(tmp_path, "K81-COR", phase="build:work",
                        rework_count={"build": "x"})
    r = _run(["abort", "K81-COR"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["rework_count"] == {"build": 1}, m["rework_count"]


# --- downstream consumer 1: metrics rollup sees the rework -------------------

def test_metrics_rollup_reflects_rework(tmp_path):
    """rework_mean is the per-track mean of sum(rework_count.values())."""
    def mk(key, track, rework):
        d = tmp_path / ".klc" / "tickets" / key
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({
            "ticket": key, "kind": "feature", "phase": "archived",
            "track": track, "estimate": {"total": 3},
            "rework_count": rework,
            "phase_history": [
                {"phase": "intake:work", "started_at": "2026-06-01T00:00:00Z",
                 "finished_at": "2026-06-01T00:01:00Z"}],
        }), encoding="utf-8")

    mk("K81-M1", "M", {"build": 2, "review": 1})   # sum 3
    mk("K81-M2", "M", {})                          # sum 0
    metrics_py = FW_ROOT / "core" / "skills" / "metrics.py"
    r = subprocess.run([sys.executable, str(metrics_py), "rollup"],
                       capture_output=True, text=True, env=_env(tmp_path))
    assert r.returncode == 0, r.stderr
    out = json.loads((tmp_path / ".klc" / "knowledge" / "process-metrics.json")
                     .read_text())
    rm = out["per_track"]["M"]["rework_mean"]
    assert abs(rm - 1.5) < 1e-9, f"rework_mean expected 1.5, got {rm}"


# --- downstream consumer 2: the learn XS/S gate fires on non-empty rework ----

def test_learn_gate_runs_on_rework_skips_without():
    """The `learn` phase condition (`... OR meta.rework_count any_overrun ...`)
    now RUNS learn for an XS/S ticket with rework, where it would otherwise skip.
    M/L always run learn regardless."""
    ph = _ph.load_phases()
    learn = ph.by_id("learn")

    skip = {"track": "S", "rework_count": {}, "regression_observed": 0,
            "budgets": {"mutation_fix_attempts": 0}}
    assert learn.should_run(skip) is False, \
        "an XS/S ticket with no failure signals must SKIP learn"

    run = {"track": "S", "rework_count": {"build": 1}, "regression_observed": 0,
           "budgets": {"mutation_fix_attempts": 0}}
    assert learn.should_run(run) is True, \
        "non-empty rework_count must make the XS/S learn gate fire"

    always = {"track": "M", "rework_count": {}, "regression_observed": 0,
              "budgets": {}}
    assert learn.should_run(always) is True, "M/L always run learn"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
