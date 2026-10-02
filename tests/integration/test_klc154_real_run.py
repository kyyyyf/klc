"""tests/integration/test_klc154_real_run.py — KLC-154 step-2, AC-2/AC-6/
AC-10: a real run rewrites every old-shape file inside exactly one
`acquire_lock` + one `state_tx` per CHANGED ticket (none for an unchanged
one), keeping every finding count and non-empty old id, and creating no
file in a changed ticket's directory other than the audit note. A ticket is
migrated regardless of its `meta.json` phase (Q-002); a `_superseded`
narrative subdirectory and a non-ticket top-level directory are left
untouched — both pin step-1's already-correct candidate set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def test_real_run_rewrites_old_shape_files_exactly_once_locked(tmp_path, monkeypatch):
    """AC-2/AC-10: one `acquire_lock` + one `state_tx` per changed ticket,
    none for an unchanged one; equal finding counts and every non-empty old
    id kept; a changed ticket's directory holds no new path other than the
    audit note."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old_changed = support.old_independent(2)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    support.add_ticket(tickets, "KLC-940", {
        "spec-review-findings.json": json.dumps(old_changed),
    })
    support.add_ticket(tickets, "KLC-941", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    support.seed_git_state(tmp_path)

    lock_calls: list = []
    tx_calls: list = []
    real_acquire_lock = findings_migrate.acquire_lock
    real_state_tx = findings_migrate.state_tx.state_tx

    def spy_lock(ticket):
        lock_calls.append(ticket)
        return real_acquire_lock(ticket)

    def spy_tx(ticket, msg):
        tx_calls.append(ticket)
        return real_state_tx(ticket, msg)

    monkeypatch.setattr(findings_migrate, "acquire_lock", spy_lock)
    monkeypatch.setattr(findings_migrate.state_tx, "state_tx", spy_tx)

    report = findings_migrate.migrate(tickets)
    rows = {r["ticket"]: r for r in report["tickets"]}

    assert rows["KLC-940"]["status"] == "rewritten", rows["KLC-940"]
    assert rows["KLC-941"]["status"] == "unchanged", rows["KLC-941"]
    assert lock_calls.count("KLC-940") == 1
    assert "KLC-941" not in lock_calls
    assert tx_calls.count("KLC-940") == 1
    assert "KLC-941" not in tx_calls

    new_json = json.loads(
        (tickets / "KLC-940" / "spec-review-findings.json").read_text(encoding="utf-8"))
    assert len(new_json) == len(old_changed)
    assert {r["id"] for r in old_changed} <= {r["id"] for r in new_json}

    seen = support.listing(tickets / "KLC-940")
    assert seen == {"meta.json", "spec-review-findings.json", findings_migrate.AUDIT_NOTE}


def test_ticket_in_any_phase_is_migrated(tmp_path, monkeypatch):
    """Q-002: a ticket is migrated regardless of its `meta.json` phase."""
    tickets = support.make_project(tmp_path, monkeypatch)
    phases = ["intake", "build:work", "review", "archived"]
    for i, phase in enumerate(phases):
        old = support.old_independent(1)
        support.add_ticket(tickets, f"KLC-95{i}", {
            "spec-review-findings.json": json.dumps(old),
        }, phase=phase)

    report = findings_migrate.migrate(tickets)
    rows = {r["ticket"]: r for r in report["tickets"]}
    for i in range(len(phases)):
        assert rows[f"KLC-95{i}"]["status"] == "rewritten", rows[f"KLC-95{i}"]


def test_superseded_narratives_and_non_ticket_dirs_are_untouched(tmp_path, monkeypatch):
    """A `_superseded` narrative subdirectory and a top-level directory with
    no `meta.json` are never visited as a ticket."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-960", {
        "spec-review-findings.json": json.dumps(old),
    })
    superseded = tdir / "_superseded"
    superseded.mkdir()
    (superseded / "spec-review-findings.json").write_text(json.dumps(old), encoding="utf-8")
    not_a_ticket = tickets / "archive"
    not_a_ticket.mkdir()
    (not_a_ticket / "notes.txt").write_text("not a ticket\n", encoding="utf-8")

    before_superseded = (superseded / "spec-review-findings.json").read_bytes()
    before_notes = (not_a_ticket / "notes.txt").read_bytes()

    report = findings_migrate.migrate(tickets)
    rows = {r["ticket"]: r for r in report["tickets"]}

    assert rows["KLC-960"]["status"] == "rewritten", rows["KLC-960"]
    assert "archive" not in rows
    assert (superseded / "spec-review-findings.json").read_bytes() == before_superseded
    assert (not_a_ticket / "notes.txt").read_bytes() == before_notes
