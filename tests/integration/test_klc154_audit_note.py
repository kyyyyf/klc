"""tests/integration/test_klc154_audit_note.py — KLC-154 step-2, AC-4: one
run entry is appended to the ticket's `migration-findings-shape.json`
(created on the first run), naming each rewritten file with its finding
count and SHA-256 before and after, leaving earlier entries untouched — and
never written for an unchanged ticket. An unreadable existing audit note
fails the ticket (before any write) rather than being silently overwritten.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def test_audit_note_appends_entry_with_sha256(tmp_path, monkeypatch):
    """AC-4: the first run creates the audit note with one entry; a
    straggler added afterwards and migrated by the second run appends a
    SECOND entry, leaving the first untouched, and every SHA-256 matches
    the actual file bytes."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-970", {
        "spec-review-findings.json": json.dumps(old),
    })

    first = findings_migrate.migrate(tickets)
    assert first["tickets"][0]["status"] == "rewritten", first["tickets"][0]

    note_path = tdir / findings_migrate.AUDIT_NOTE
    runs_after_first = json.loads(note_path.read_text(encoding="utf-8"))
    assert len(runs_after_first) == 1
    entry0 = runs_after_first[0]
    current = (tdir / "spec-review-findings.json").read_bytes()
    assert entry0["files"][0]["sha256_after"] == hashlib.sha256(current).hexdigest()

    # a straggler old-shape file added to the SAME ticket after the first run
    straggler = support.old_independent(1)
    (tdir / "test-plan-review-findings.json").write_text(
        json.dumps(straggler), encoding="utf-8")

    second = findings_migrate.migrate(tickets)
    row = second["tickets"][0]
    assert row["status"] == "rewritten", row

    runs_after_second = json.loads(note_path.read_text(encoding="utf-8"))
    assert len(runs_after_second) == 2
    assert runs_after_second[0] == entry0  # the earlier entry is untouched
    new_current = (tdir / "test-plan-review-findings.json").read_bytes()
    assert runs_after_second[1]["files"][0]["sha256_after"] == hashlib.sha256(new_current).hexdigest()


def test_audit_note_not_written_for_unchanged_ticket(tmp_path, monkeypatch):
    """A ticket already in the one shape takes no lock, enters no
    transaction, and gets no audit note at all."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    tdir = support.add_ticket(tickets, "KLC-972", {
        "spec-review-findings.json": json.dumps(one_shape),
    })

    report = findings_migrate.migrate(tickets)
    assert report["tickets"][0]["status"] == "unchanged"
    assert not (tdir / findings_migrate.AUDIT_NOTE).exists()


def test_unreadable_audit_note_fails_the_ticket(tmp_path, monkeypatch):
    """An existing-but-corrupt audit note fails the ticket's plan (before
    any write) instead of being silently overwritten."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    raw = json.dumps(old)
    tdir = support.add_ticket(tickets, "KLC-973", {
        "spec-review-findings.json": raw,
        findings_migrate.AUDIT_NOTE: "{not valid json",
    })

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "failed"
    assert (tdir / "spec-review-findings.json").read_text(encoding="utf-8") == raw
