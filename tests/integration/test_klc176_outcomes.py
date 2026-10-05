"""KLC-176 step-4 (AC-8, AC-11): manual and integrate outcomes live in meta.json.

`klc ack --note` records meta.manual = {verdict, note, at}; the integrate ack
records meta.integrate = {branch_head, main_head, at}. Neither phase declares an output file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle  # noqa: E402
import phases  # noqa: E402
from core.shared import yaml as project_yaml  # noqa: E402
from core.skills.phase_completion import can_complete  # noqa: E402


def _seed(tmp_path: Path, key: str, phase: str) -> Path:
    tdir = tmp_path / ".klc/tickets" / key
    tdir.mkdir(parents=True)
    (tdir / "meta.json").write_text(json.dumps({
        "ticket": key, "kind": "feature", "phase": phase, "track": "M",
        "phase_history": [{"phase": phase, "started_at": "2026-10-01T00:00:00Z"}],
    }), encoding="utf-8")
    return tdir


def _meta(tdir: Path) -> dict:
    return json.loads((tdir / "meta.json").read_text("utf-8"))


def test_manual_ack_records_verdict_note_at(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-920", "manual:ack-needed")
    lifecycle.apply_ack("KLC-920", 1, "walked all ACs on staging")
    manual = _meta(tdir)["manual"]
    assert manual["verdict"] == "passed"
    assert manual["note"] == "walked all ACs on staging"
    assert manual["at"].endswith("Z")
    assert not (tdir / "manual-checklist.md").exists()


def test_integrate_ack_records_both_heads(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "T"),
                 ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty",
                    "-m", "m"], check=True)
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    tdir = _seed(tmp_path, "KLC-921", "integrate:ack-needed")
    lifecycle.apply_ack("KLC-921", None)
    integ = _meta(tdir)["integrate"]
    assert integ["branch_head"] == head
    assert "merge_sha" not in integ
    assert integ["main_head"] is None or isinstance(integ["main_head"], str)
    assert integ["at"].endswith("Z")
    assert not (tdir / "integrate.md").exists()


def test_manual_and_integrate_need_no_output_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    by_id = {p["id"]: p for p in project_yaml.load(_FW / "config" / "phases.yml")["phases"]}
    assert not by_id["manual"].get("outputs")
    assert not by_id["integrate"].get("outputs")
    jira = project_yaml.load(_FW / "config" / "jira.yml")["artifacts"]["paths"]
    assert jira["manual"] == jira["integrate"] == "review-report.md"
    _seed(tmp_path, "KLC-922", "manual:work")
    ok, msg = can_complete("KLC-922", "manual", persist=False)
    assert ok, msg


def test_old_ticket_with_checklist_unaffected(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-923", "manual:ack-needed")
    (tdir / "manual-checklist.md").write_text("- [x] AC-1\n", encoding="utf-8")
    ok, _ = can_complete("KLC-923", "manual", persist=False)
    assert ok
    lifecycle.apply_ack("KLC-923", 2)           # failed: reopens build
    assert _meta(tdir)["manual"]["verdict"] == "failed"
