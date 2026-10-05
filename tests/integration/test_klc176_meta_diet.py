"""KLC-176 step-4 (AC-7, AC-11): meta.json stops carrying write-only keys.

New tickets do not get kind_source, route_signals, route_decision, mentions,
links, blast_radius, design_choice, the full metrics.retrieval record (a compact one stays) or a note that repeats
the pick. The metrics rollup keeps reading old metas and falls back to the
derived retrieval-eval.jsonl row for new ones.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle  # noqa: E402
import metrics as _metrics  # noqa: E402
import retrieval_eval as _reval  # noqa: E402

_DROPPED = ("kind_source", "route_signals", "route_decision", "mentions", "links",
            "related_tickets", "blast_radius", "design_choice")
_KEPT = ("route_hint", "route_confidence", "track", "affected_modules",
         "rework_count", "phase", "estimate", "layer")


def _klc(project: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PROJECT_ROOT=str(project))
    return subprocess.run([sys.executable, str(_FW / "scripts" / "klc"), *args],
                          cwd=str(project), env=env, capture_output=True, text=True)


def _git_project(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "T"),
                 ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty",
                    "-m", "init"], check=True)
    return tmp_path


def test_new_ticket_meta_lacks_write_only_keys(tmp_path):
    proj = _git_project(tmp_path)
    r = _klc(proj, "intake", "--kind", "tech", "--no-index-refresh",
             "KLC-901", "fix a typo in the readme")
    assert r.returncode == 0, r.stderr
    r = _klc(proj, "ack", "KLC-901", "--pick", "1", "--no-index-refresh")
    assert r.returncode == 0, r.stderr
    meta = json.loads((proj / ".klc/tickets/KLC-901/meta.json").read_text("utf-8"))
    for key in _DROPPED:
        assert key not in meta, key
    assert "retrieval" not in (meta.get("metrics") or {})
    for key in _KEPT:
        assert key in meta, key
    for entry in meta["phase_history"]:
        assert not str(entry.get("note", "")).startswith(("pick=", "ack:")), entry


def test_ack_note_text_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc/tickets/KLC-902"
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps({
        "ticket": "KLC-902", "kind": "feature", "phase": "design:ack-needed",
        "track": "M", "phase_history": [{"phase": "design:ack-needed",
                                         "started_at": "2026-10-01T00:00:00Z"}],
    }), encoding="utf-8")
    lifecycle.apply_ack("KLC-902", 1)
    meta = json.loads((tdir / "meta.json").read_text("utf-8"))
    assert "design_choice" not in meta
    ack = [e for e in meta["phase_history"] if e.get("event") == "ack"][-1]
    assert ack["pick"] == {"id": 1, "label": "option-A-minimal"}
    assert not any(str(e.get("note", "")).startswith(("pick=", "ack:"))
                   for e in meta["phase_history"])
    # started_at / finished_at stay (the cycle time reads them)
    assert all("started_at" in e for e in meta["phase_history"])


def test_consume_stages_compact_record_and_keeps_derived_row(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc/tickets/KLC-903"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"phase": "integrate:work", "track": "M", "metrics": {}}), encoding="utf-8")
    trace = {"status": "ok", "confidence": "medium", "files_likely_to_edit": ["a.py"],
             "files_to_read_first": [], "tests_to_read_or_run": [],
             "affected_modules_hint": []}
    rec = _reval.consume("KLC-903", trace, set(), {"a.py"}, "M", persist=True)
    lifecycle.set_state("KLC-903", "integrate", "ack-needed")
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    compact = meta["metrics"]["retrieval"]
    assert set(compact) == {"score", "confidence", "at"}
    assert compact["confidence"] == "medium"
    assert _reval.logged_record("KLC-903")["status"] == rec["status"] == "ok"
    assert _reval.logged_record("KLC-NONE") is None


def _ticket(root: Path, key: str, metrics: dict | None) -> None:
    d = root / ".klc/tickets" / key
    d.mkdir(parents=True)
    meta = {"ticket": key, "kind": "tech", "phase": "archived", "track": "M",
            "phase_history": [{"phase": "intake:work", "started_at": "2026-06-01T00:00:00Z",
                               "finished_at": "2026-06-01T00:01:00Z"}]}
    if metrics is not None:
        meta["metrics"] = metrics
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _rec(p5):
    return {"status": "ok", "confidence": "low", "degraded_inputs": [],
            "files_likely_to_edit": {"precision": p5, "recall": 0.5, "candidates": 1},
            "files_to_read_first": {"precision": 0.5, "recall": 0.5,
                                    "items_before_first_hit": 1},
            "tests_to_read_or_run": {"recall": 0.5},
            "affected_modules_hint": {"precision": 0.5, "recall": 0.5,
                                      "is_subset": True, "is_superset": True}}


def _rollup(root: Path, monkeypatch) -> dict:
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    (root / ".klc/knowledge").mkdir(parents=True, exist_ok=True)
    _metrics.cmd_rollup(argparse.Namespace(output=None))
    return json.loads((root / ".klc/knowledge/process-metrics.json").read_text("utf-8"))


def test_rollup_mixes_old_and_new_metas(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-910", {"retrieval": _rec(1.0)})   # old meta carries it
    _ticket(tmp_path, "KLC-911", {})                          # new meta: only the row
    _reval.append_log("KLC-911", "M", _rec(0.0))
    out = _rollup(tmp_path, monkeypatch)
    r = out["per_track"]["M"]["retrieval"]
    assert r["tickets_scored"] == 2
    assert r["zero_precision_at_5_tickets"] == ["KLC-911"]
    assert out["per_confidence"]["low"]["tickets"] == 2
    assert out["per_confidence"]["no_record"]["tickets"] == 0


def test_metrics_rollup_runs_over_real_tickets(tmp_path, monkeypatch):
    real = _FW / ".klc" / "tickets"
    if not real.is_dir():
        return
    import shutil
    shutil.copytree(real, tmp_path / ".klc" / "tickets",
                    ignore=shutil.ignore_patterns("_superseded"))
    out = _rollup(tmp_path, monkeypatch)
    assert out["tickets_total"] > 0
