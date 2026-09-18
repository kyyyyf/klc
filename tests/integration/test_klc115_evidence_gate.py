"""KLC-115 step-3: core/skills/evidence_gate.check_evidence — per-AC
coverage, re-execution, track scaling, and the surface-not-block rule for
`unverified` (AC-4, AC-5, AC-6, AC-15, AC-18, plus the F-4/D-204 addendum).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import evidence_gate as eg  # noqa: E402
import verify_runner as vr  # noqa: E402


def _make_ticket(tmp_path, ticket, track, spec_acs, evidence_body, meta_extra=None):
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": track,
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    meta.update(meta_extra or {})
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    spec_lines = ["---", f"ticket: {ticket}", "kind: feature", "---", "",
                 "## Acceptance Criteria"]
    for ac in spec_acs:
        spec_lines.append(f"- [ ] {ac}: subject · acts · object · when a thing happens")
    (ticket_dir / "spec.md").write_text("\n".join(spec_lines), encoding="utf-8")
    build_log = (f"---\nticket: {ticket}\nkind: build-log\n---\n\n"
                f"# Build log — {ticket}\n\n## Evidence\n\n{evidence_body}\n")
    (ticket_dir / "build-log.md").write_text(build_log, encoding="utf-8")
    return ticket_dir


def test_ac_with_no_evidence_entry_blocks_on_track_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG01"
    _make_ticket(tmp_path, ticket, "M", ["AC-1", "AC-2", "AC-3", "AC-4"],
                "### AC-1, AC-2, AC-3 — three of four\n\n```\n$ echo ok\nok\n```\n")
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert rep.block_reason
    assert "AC-4" in rep.block_reason


def test_missing_evidence_section_blocks_on_track_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG02"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        "---\nticket: KLC-EG02\nkind: feature\n---\n\n## Acceptance Criteria\n"
        "- [ ] AC-1: subject · acts · object · when a thing happens\n",
        encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(
        "---\nticket: KLC-EG02\nkind: build-log\n---\n\n# Build log\n\n"
        "## Step 1\n**Outcome**: green\n", encoding="utf-8")
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert rep.block_reason
    assert "AC-1" in rep.block_reason


def test_persisting_ack_reexecutes_every_entry_command_in_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG03"
    _make_ticket(tmp_path, ticket, "M", ["AC-1"],
                "### AC-1 — proof\n\n```\n$ echo ok\nok\n```\n")
    calls = []
    real_run = eg.verify_runner.run

    def spy(command, *, budget_s, cwd=None, **kw):
        calls.append({"command": command, "budget_s": budget_s, "cwd": cwd})
        return real_run(command, budget_s=budget_s, cwd=cwd, **kw)

    monkeypatch.setattr(eg.verify_runner, "run", spy)
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason, rep.block_reason
    assert calls, "the entry's command must be re-executed"
    assert calls[0]["cwd"] == str(tmp_path)
    assert calls[0]["budget_s"] == eg.settings.verify_entry_budget()


def test_pass_entry_that_fails_on_rerun_blocks_on_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG04"
    _make_ticket(tmp_path, ticket, "M", ["AC-1"],
                "### AC-1 — claims pass but doesn't\n\n"
                "```\n$ python3 -c \"import sys; sys.exit(1)\"\nboom\n```\n")
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert rep.block_reason
    assert "AC-1" in rep.block_reason


def test_fixture_prose_with_one_unattributed_fence_rejected_on_m(tmp_path, monkeypatch):
    sys.path.insert(0, str(FRAMEWORK_ROOT))
    from core.skills.phase_completion import can_complete_build

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG05"
    _make_ticket(tmp_path, ticket, "M", ["AC-1"],
                "AC verification (all satisfied) — everything was checked by hand "
                "and looked correct.\n\n```\n$ pytest tests/ -q\n5 passed\n```\n")
    ok, msg = can_complete_build(ticket)
    assert not ok, f"expected False, got {msg!r}"
    assert "AC-1" in msg


def test_budget_exceeded_entry_surfaces_not_blocks_on_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG06"
    _make_ticket(tmp_path, ticket, "M", ["AC-1"],
                "### AC-1 — genuinely passes, just slowly\n\n"
                "```\n$ python3 -c \"import time; time.sleep(2)\"\nslow but fine\n```\n")
    monkeypatch.setattr(eg.settings, "verify_entry_budget", lambda: 1)
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason, rep.block_reason
    text = " ".join(f.message for f in rep.surfaced)
    assert "unverified" in text
    assert "budget-exceeded" in text


def test_launch_error_entry_surfaces_not_blocks_on_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG07"
    _make_ticket(tmp_path, ticket, "M", ["AC-1"],
                "### AC-1 — proof\n\n```\n$ some-binary-that-is-never-launched\nn/a\n```\n")

    def fake_run(command, *, budget_s, cwd=None, **kw):
        return vr.Verdict(vr.UNVERIFIED, vr.LAUNCH_ERROR,
                          "could not launch the command (FileNotFoundError)")

    monkeypatch.setattr(eg.verify_runner, "run", fake_run)
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason, rep.block_reason
    text = " ".join(f.message for f in rep.surfaced)
    assert "unverified" in text
    assert "launch-error" in text


def test_arm_budget_exhaustion_surfaces_remaining_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-EG08"
    _make_ticket(tmp_path, ticket, "M", ["AC-1", "AC-2"],
                "### AC-1 — proof\n\n```\n$ echo ok\nok\n```\n\n"
                "### AC-2 — proof\n\n```\n$ echo ok\nok\n```\n")
    monkeypatch.setattr(eg.settings, "verify_arm_budget", lambda: -1)
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason, rep.block_reason
    codes = {f.ac_id: f.code for f in rep.surfaced}
    assert codes.get("AC-1") == "unverified-arm-budget-exhausted"
    assert codes.get("AC-2") == "unverified-arm-budget-exhausted"
