"""KLC-076 feature-OFF unit coverage for the `cancelled` terminal:

  - `klc abort --cancel` is a pure local write when the multi-user feature is
    OFF (no git touched);
  - a cancelled ticket is terminal — ack/next/ship/jump/abort refuse it;
  - status (text + --json), board and work render it without error and never as
    active/pending;
  - metrics count `cancelled` distinctly from `archived` (excluded from
    completion / throughput);
  - plain `abort` behaviour is unchanged;
  - the phases.py primitive recognises `cancelled` as terminal.

These run feature-OFF (no `.klc` git worktree) so state_tx is a no-op.
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
               artefacts: dict | None = None) -> Path:
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase,
        "phase_history": [{"phase": phase, "started_at": "2026-01-01T00:00:00Z",
                           "finished_at": "2026-01-02T00:00:00Z"}],
        "track": track, "route_hint": track, "affected_modules": [],
        "budgets": {"mutation_fix_attempts": 3},
        "estimate": None, "jira_url": None, "created": "2026-01-01T00:00:00Z",
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


# --- phases.py primitive ------------------------------------------------------

def test_phases_recognises_cancelled_terminal():
    assert _ph.is_terminal("cancelled") is True
    assert _ph.is_terminal("archived") is True
    assert _ph.is_terminal("build:work") is False
    assert _ph.parse_state("cancelled") == ("cancelled", "cancelled")
    assert _ph.format_state("cancelled", "cancelled") == "cancelled"


# --- feature-OFF cancel is a pure local write --------------------------------

def test_cancel_feature_off_local_write_from_work(tmp_path):
    root = tmp_path
    meta_p = _bootstrap(root, "T76-1", phase="build:work",
                        artefacts={"build/impl-plan.md": "x\n"})
    r = _run(["abort", "T76-1", "--cancel", "--reason", "not needed"], root)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "cancelled" and m["cancelled"] is True
    assert m["cancel_reason"] == "not needed"
    entry = next(e for e in m["phase_history"] if e.get("event") == "cancelled")
    assert entry["from_phase"] == "build:work" and entry["reason"] == "not needed"
    assert "by" in entry
    # From :work the current-phase artefacts are moved to _superseded/.
    assert not (root / ".klc/tickets/T76-1/build/impl-plan.md").exists()
    assert list((root / ".klc/tickets/T76-1/_superseded").glob("*/build/**/impl-plan.md"))
    # feature-off touches no git.
    assert not (root / ".klc" / ".git").exists()


def test_cancel_feature_off_from_ack_and_intake(tmp_path):
    for tk, ph in (("T76-A", "design:ack"), ("T76-B", "intake:ack-needed")):
        meta_p = _bootstrap(tmp_path, tk, phase=ph)
        r = _run(["abort", tk, "--cancel", "--reason", "obsolete"], tmp_path)
        assert r.returncode == 0, r.stderr
        m = json.loads(meta_p.read_text())
        assert m["phase"] == "cancelled"
        entry = next(e for e in m["phase_history"] if e.get("event") == "cancelled")
        assert entry["from_phase"] == ph


# --- terminal: every advance verb refuses ------------------------------------

@pytest.mark.parametrize("verb,extra", [
    ("ack", []),
    ("next", []),
    ("ship", []),
    ("jump", ["design"]),
    ("abort", []),           # plain abort refuses a terminal ticket
    ("steal", []),           # steal refuses a terminal ticket (KLC-076 fix)
])
def test_cancelled_ticket_refuses_advance(tmp_path, verb, extra):
    meta_p = _bootstrap(tmp_path, "T76-T", phase="cancelled")
    before = meta_p.read_bytes()
    # jump takes `<phase> <ticket>`; the rest take `<ticket>`.
    argv = [verb, *extra, "T76-T"] if verb == "jump" else [verb, "T76-T", *extra]
    r = _run(argv, tmp_path)
    assert r.returncode != 0, f"{verb} must refuse a cancelled ticket: {r.stdout}"
    assert "cancelled" in (r.stdout + r.stderr).lower()
    # A refused verb must not partially mutate the ticket before refusing.
    assert meta_p.read_bytes() == before, \
        f"{verb} mutated a cancelled ticket's meta before refusing"


def test_archived_ticket_refuses_steal(tmp_path):
    """The terminal-refusal in steal covers archived too, not only cancelled."""
    meta_p = _bootstrap(tmp_path, "T76-AR", phase="archived")
    before = meta_p.read_bytes()
    r = _run(["steal", "T76-AR"], tmp_path)
    assert r.returncode != 0
    assert "archived" in (r.stdout + r.stderr).lower()
    assert meta_p.read_bytes() == before


def test_recancel_refused(tmp_path):
    _bootstrap(tmp_path, "T76-RC", phase="cancelled")
    r = _run(["abort", "T76-RC", "--cancel", "--reason", "again"], tmp_path)
    assert r.returncode == 1
    assert "already cancelled" in r.stderr


# --- render: status / board / work never crash, never "active" ---------------

def test_status_renders_cancelled(tmp_path):
    _bootstrap(tmp_path, "T76-S", phase="cancelled")
    r = _run(["status", "T76-S"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "cancelled" in r.stdout.lower()
    assert "now ·" not in r.stdout, "cancelled must not render an active-phase row"

    rj = _run(["status", "T76-S", "--json"], tmp_path)
    assert rj.returncode == 0, rj.stderr
    obj = json.loads(rj.stdout)
    assert obj["phase"] == "cancelled" and obj["state"] == "cancelled"


def test_board_buckets_cancelled_separately(tmp_path):
    _bootstrap(tmp_path, "T76-BC", phase="cancelled")
    _bootstrap(tmp_path, "T76-BL", phase="build:work")
    r = _run(["board", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "cancelled" in data, "cancelled ticket must bucket under its own key"
    assert data["cancelled"][0]["key"] == "T76-BC"
    # It must NOT appear under any active-phase bucket.
    active_keys = [rec["key"] for k, recs in data.items()
                   if k not in ("cancelled", "archived") for rec in recs]
    assert "T76-BC" not in active_keys


def test_work_reports_nothing_to_do(tmp_path):
    _bootstrap(tmp_path, "T76-W", phase="cancelled")
    r = _run(["work", "T76-W"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "cancelled" in r.stdout.lower() and "nothing to do" in r.stdout.lower()


# --- run / autorunner: a cancelled ticket is a CLEAN terminal (exit 0) -------

def test_run_on_cancelled_ticket_exits_zero(tmp_path):
    """MEDIUM (codex P2): `klc run` on a cancelled ticket is a clean terminal
    stop (exit 0, 'DONE (cancelled)'), NOT a refusal (exit 1)."""
    _bootstrap(tmp_path, "T76-RUN", phase="cancelled")
    r = _run(["run", "T76-RUN"], tmp_path)
    assert r.returncode == 0, f"cancelled must be a clean terminal: {r.stderr}"
    assert "DONE (cancelled)" in r.stdout, r.stdout

    rj = _run(["run", "T76-RUN", "--json"], tmp_path)
    assert rj.returncode == 0
    obj = json.loads(rj.stdout)
    assert obj["terminal"] == "cancelled" and obj["reason"] is None


def test_run_on_archived_ticket_still_exits_zero(tmp_path):
    """Parity: archived stays a clean terminal exit 0 ('DONE (archived)')."""
    _bootstrap(tmp_path, "T76-RUNA", phase="archived")
    r = _run(["run", "T76-RUNA"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "DONE (archived)" in r.stdout, r.stdout


def test_autorunner_returns_terminal_flag_for_cancelled(tmp_path, monkeypatch):
    """autorunner.run reports a cancelled terminal via `terminal`, reason=None
    (a set reason with no paused_at would read as a refusal)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _bootstrap(tmp_path, "T76-AR2", phase="cancelled")
    import autorunner
    res = autorunner.run("T76-AR2")
    assert res.terminal == "cancelled"
    assert res.reason is None and res.paused_at is None


# --- metrics: cancelled distinct from archived -------------------------------

def test_metrics_excludes_cancelled_counts_archived(tmp_path):
    _bootstrap(tmp_path, "M76-DONE", phase="archived")
    _bootstrap(tmp_path, "M76-CANC", phase="cancelled")
    _bootstrap(tmp_path, "M76-LIVE", phase="build:work")
    metrics_py = FW_ROOT / "core" / "skills" / "metrics.py"
    r = subprocess.run([sys.executable, str(metrics_py), "rollup"],
                       capture_output=True, text=True, env=_env(tmp_path))
    assert r.returncode == 0, r.stderr
    out = json.loads((tmp_path / ".klc" / "knowledge" / "process-metrics.json")
                     .read_text())
    # archived + live are counted; cancelled is excluded and counted separately.
    assert out["cancelled_total"] == 1
    assert out["tickets_total"] == 2


# --- plain abort unchanged ----------------------------------------------------

def test_plain_abort_unchanged(tmp_path):
    meta_p = _bootstrap(tmp_path, "T76-PA", phase="build:work")
    r = _run(["abort", "T76-PA"], tmp_path)
    assert r.returncode == 0, r.stderr
    m = json.loads(meta_p.read_text())
    assert m["phase"] == "design:ack", "plain abort steps back to previous :ack"
    assert m.get("cancelled") is not True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
