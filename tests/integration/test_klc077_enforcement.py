"""KLC-077 — real-substrate `:work`-entry enforcement (feature-OFF).

Drives real `klc` verbs against a temp PROJECT_ROOT with the multi-user feature
OFF. The dependency gate is a SINGLE choke point in `lifecycle.enter_work_guard`,
so EVERY `:work`-entry path must honour it — next, ack, ship, jump, and
run/autorunner. Each refuses/pauses while the upstream is short of the point and
proceeds once it is reached. A ticket with no edges advances unchanged.

Feature-OFF resting states after a block:
  - `next` (from `:ack`): the guard fires before any write → the ticket stays at
    its `:ack` (unchanged).
  - `ack`/`ship` (approve from `:ack-needed`): the pick's `:ack` is recorded, then
    the advance into the gated `:work` is refused → the ticket rests at `:ack`
    (a valid, re-runnable state; `klc next` proceeds once unblocked).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
KLC = FW_ROOT / "scripts" / "klc"


def _env(root: Path) -> dict[str, str]:
    e = {**os.environ, "PROJECT_ROOT": str(root)}
    e.pop("KLC_TICKETS_DIR", None)
    return e


def _run(args: list[str], root: Path):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=_env(root))


def _bootstrap(root: Path, ticket: str, *, phase: str, track: str = "S",
               blocked_by: list[dict] | None = None,
               phase_history: list[dict] | None = None, **extra) -> Path:
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase,
        "phase_history": phase_history or [
            {"phase": phase, "started_at": "2026-01-01T00:00:00Z"}],
        "track": track, "route_hint": track, "affected_modules": [],
        "risk_tags": [], "budgets": {"mutation_fix_attempts": 0},
        "estimate": None, "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if blocked_by is not None:
        meta["blocked_by"] = blocked_by
    meta.update(extra)
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return tdir / "meta.json"


def _phase(root: Path, key: str) -> str:
    return json.loads((root / ".klc" / "tickets" / key / "meta.json")
                      .read_text(encoding="utf-8"))["phase"]


_EDGE = {"on": "UP", "phase": "build", "point": "integrated"}


# --- klc next -----------------------------------------------------------------

def test_next_refuses_then_unblocks_via_real_upstream_transition(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="integrate:work", track="S")
    _bootstrap(root, "DOWN", phase="discovery-lite:ack", track="S",
               blocked_by=[_EDGE])

    r = _run(["next", "DOWN"], root)
    assert r.returncode != 0, r.stdout
    assert "blocked by UP until integrated" in r.stderr
    assert _phase(root, "DOWN") == "discovery-lite:ack"

    # Drive the REAL upstream past the point (ack integrate → archived).
    r = _run(["ack", "UP"], root)
    assert r.returncode == 0, r.stderr
    assert _phase(root, "UP") in ("archived", "observe:work", "learn:work")

    r = _run(["next", "DOWN"], root)
    assert r.returncode == 0, r.stderr
    assert _phase(root, "DOWN") == "build:work"


# --- klc ack (approve → advance) ---------------------------------------------

def test_ack_approve_refuses_then_unblocks(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="build:ack", track="S")   # short of integrated
    _bootstrap(root, "DOWN", phase="discovery-lite:ack-needed", track="S",
               blocked_by=[_EDGE])

    r = _run(["ack", "DOWN", "--pick", "1"], root)
    assert r.returncode != 0, r.stdout
    assert "blocked by UP until integrated" in r.stderr
    # The pick's :ack is recorded; the advance into build:work is refused.
    assert _phase(root, "DOWN") == "discovery-lite:ack"

    _bootstrap(root, "UP", phase="integrate:ack", track="S")  # reached
    r = _run(["next", "DOWN"], root)
    assert r.returncode == 0, r.stderr
    assert _phase(root, "DOWN") == "build:work"


# --- klc ship (ack + next) ---------------------------------------------------

def test_ship_refuses_while_blocked_and_proceeds_when_unblocked(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="build:ack", track="S")   # short
    _bootstrap(root, "DOWN", phase="discovery-lite:ack-needed", track="S",
               blocked_by=[_EDGE])
    r = _run(["ship", "DOWN", "--pick", "1"], root)
    assert r.returncode != 0, r.stdout
    assert "blocked by UP until integrated" in r.stderr
    assert _phase(root, "DOWN") == "discovery-lite:ack"

    # A fresh downstream, upstream now reached → ship advances into build:work.
    _bootstrap(root, "UP", phase="integrate:ack", track="S")
    _bootstrap(root, "DOWN2", phase="discovery-lite:ack-needed", track="S",
               blocked_by=[_EDGE])
    r = _run(["ship", "DOWN2", "--pick", "1"], root)
    assert r.returncode == 0, r.stderr
    assert _phase(root, "DOWN2") == "build:work"


# --- klc jump (operator escape hatch is gated too) ---------------------------

def test_jump_refuses_blocked_target_then_proceeds(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="build:ack", track="S")   # short
    _bootstrap(root, "DOWN", phase="discovery-lite:ack", track="S",
               blocked_by=[_EDGE])
    r = _run(["jump", "build", "DOWN", "--yes"], root)
    assert r.returncode != 0, r.stdout
    assert "blocked by UP until integrated" in r.stderr
    assert _phase(root, "DOWN") == "discovery-lite:ack"

    _bootstrap(root, "UP", phase="integrate:ack", track="S")  # reached
    r = _run(["jump", "build", "DOWN", "--yes"], root)
    assert r.returncode == 0, r.stderr
    assert _phase(root, "DOWN") == "build:work"


# --- klc run / autorunner (lingering :ack advance is gated → clean pause) ----

def test_run_autorunner_pauses_on_block_then_advances(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="build:ack", track="S")   # short
    _bootstrap(root, "DOWN", phase="discovery-lite:ack", track="S",
               blocked_by=[_EDGE])
    r = _run(["run", "DOWN"], root)
    # Clean decision-gate-style pause (rc 2), NOT a crash/refusal error.
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "blocked by UP until integrated" in (r.stdout + r.stderr)
    assert _phase(root, "DOWN") == "discovery-lite:ack"   # did not advance

    _bootstrap(root, "UP", phase="integrate:ack", track="S")  # reached
    r = _run(["run", "DOWN"], root)
    # Now the lingering :ack advances into build:work (autorunner then dispatches
    # / pauses further downstream — we only assert it left the gated :ack).
    assert _phase(root, "DOWN") != "discovery-lite:ack"


# --- P1-B: a blocked explicit-jump pick mutates NOTHING (feature-OFF) --------

def test_blocked_explicit_jump_pick_leaves_ticket_byte_unchanged(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="build:ack", track="S")   # short of integrated
    # DOWN at observe:ack-needed; pick 2 (regression) → build:work + supersedes
    # the review artifact. The build edge must block BEFORE the ack/supersede.
    meta_p = _bootstrap(root, "DOWN", phase="observe:ack-needed", track="S",
                        blocked_by=[_EDGE])
    report = root / ".klc" / "tickets" / "DOWN" / "review-report.md"
    report.write_text("verdict: approve\n", encoding="utf-8")

    before = meta_p.read_bytes()
    r = _run(["ack", "DOWN", "--pick", "2"], root)   # regression → build:work
    assert r.returncode != 0, r.stdout
    assert "blocked by UP until integrated" in r.stderr
    # Byte-unchanged meta, artifact NOT superseded, no _superseded dir created.
    assert meta_p.read_bytes() == before
    assert report.exists() and report.read_text() == "verdict: approve\n"
    assert not (root / ".klc" / "tickets" / "DOWN" / "_superseded").exists()


# --- condition `passed`: reached but tainted → block for a human -------------

def test_next_condition_passed_blocks_on_regression(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="archived", track="S", regression_observed=1,
               phase_history=[
                   {"phase": "integrate:ack", "event": "ack",
                    "pick": {"id": 1, "label": "merged"}},
                   {"phase": "observe:ack", "event": "ack",
                    "pick": {"id": 2, "label": "regression"}}])
    _bootstrap(root, "DOWN", phase="discovery-lite:ack", track="S",
               blocked_by=[{"on": "UP", "phase": "build",
                            "point": "integrated", "condition": "passed"}])
    r = _run(["next", "DOWN"], root)
    assert r.returncode != 0, r.stdout
    assert "needs a human" in r.stderr.lower()
    assert _phase(root, "DOWN") == "discovery-lite:ack"


# --- dangling / cancelled upstream -------------------------------------------

def test_next_dangling_upstream_refuses(tmp_path):
    root = tmp_path
    _bootstrap(root, "DOWN", phase="discovery-lite:ack", track="S",
               blocked_by=[{"on": "GHOST", "phase": "build",
                            "point": "integrated"}])
    r = _run(["next", "DOWN"], root)
    assert r.returncode != 0, r.stdout
    assert "GHOST" in r.stderr and "not found" in r.stderr
    assert _phase(root, "DOWN") == "discovery-lite:ack"


def test_next_cancelled_upstream_refuses_with_distinct_message(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="cancelled", track="S")
    _bootstrap(root, "DOWN", phase="discovery-lite:ack", track="S",
               blocked_by=[_EDGE])
    r = _run(["next", "DOWN"], root)
    assert r.returncode != 0, r.stdout
    assert "cancelled" in r.stderr and "will not reach" in r.stderr
    assert _phase(root, "DOWN") == "discovery-lite:ack"


# --- no edges → pure no-op (non-epic ticket unaffected) ----------------------

def test_next_no_edges_advances_unchanged(tmp_path):
    root = tmp_path
    _bootstrap(root, "NORM", phase="discovery-lite:ack", track="S")
    r = _run(["next", "NORM"], root)
    assert r.returncode == 0, r.stderr
    assert _phase(root, "NORM") == "build:work"


def test_next_edge_for_other_phase_does_not_block(tmp_path):
    root = tmp_path
    _bootstrap(root, "UP", phase="build:ack", track="S")
    _bootstrap(root, "DOWN", phase="discovery-lite:ack", track="S",
               blocked_by=[{"on": "UP", "phase": "review", "point": "integrated"}])
    r = _run(["next", "DOWN"], root)
    assert r.returncode == 0, r.stderr
    assert _phase(root, "DOWN") == "build:work"
