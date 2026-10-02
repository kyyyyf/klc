"""tests/integration/test_klc154_dry_run.py — KLC-154 step-5, AC-1: a dry
run prints the same per-file plan a real run would carry out, with counts
before/after and every failed ticket's reason, takes no lock, enters no
transaction, and writes nothing — a would-be-locked ticket is listed
`would-rewrite` and the lock is never even attempted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402
import handback  # noqa: E402


def test_dry_run_prints_plan_and_writes_nothing(tmp_path, monkeypatch, capsys):
    """AC-1: a dry run prints the plan, takes no lock, enters no
    transaction, and writes nothing; an unexpected-exception ticket is
    listed failed and every other ticket is still reported."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(2)
    support.add_ticket(tickets, "KLC-990", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.add_ticket(tickets, "KLC-991", {
        "spec-review-findings.json": "{not valid json",
    })
    bad = support.old_independent(1)
    bad[0]["id"] = "DRY-VICTIM"
    support.add_ticket(tickets, "KLC-993", {
        "spec-review-findings.json": json.dumps(bad),
    })

    before = support.tree_hashes(tickets)

    lock_calls: list = []
    tx_calls: list = []
    real_acquire_lock = findings_migrate.acquire_lock
    real_state_tx = findings_migrate.state_tx.state_tx
    real_map_findings = findings_migrate.map_findings

    def spy_lock(ticket):
        lock_calls.append(ticket)
        return real_acquire_lock(ticket)

    def spy_tx(ticket, msg):
        tx_calls.append(ticket)
        return real_state_tx(ticket, msg)

    def boom(items, kind, *, stamp=False):
        if items and isinstance(items[0], dict) and items[0].get("id") == "DRY-VICTIM":
            raise TypeError("boom for KLC-993 only")
        return real_map_findings(items, kind, stamp=stamp)

    monkeypatch.setattr(findings_migrate, "acquire_lock", spy_lock)
    monkeypatch.setattr(findings_migrate.state_tx, "state_tx", spy_tx)
    monkeypatch.setattr(findings_migrate, "map_findings", boom)

    report = findings_migrate.migrate(tickets, dry_run=True)
    rows = {r["ticket"]: r for r in report["tickets"]}

    assert rows["KLC-990"]["status"] == "would-rewrite", rows["KLC-990"]
    assert rows["KLC-991"]["status"] == "failed", rows["KLC-991"]
    assert rows["KLC-993"]["status"] == "failed", rows["KLC-993"]
    assert support.tree_hashes(tickets) == before
    assert not lock_calls
    assert not tx_calls

    code = handback.main(["migrate", "--tickets-root", str(tickets), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 1
    assert "2 -> 2 findings" in out
    assert "KLC-991" in out


def test_dry_run_does_not_see_a_held_lock(tmp_path, monkeypatch):
    """AC-1 (spec wording): a dry run lists a would-be-locked ticket as
    would-rewrite and exits 0 — the lock is never attempted."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-992", {
        "spec-review-findings.json": json.dumps(old),
    })

    def fake_acquire_lock(ticket):
        raise findings_migrate.LockedError(f"ticket {ticket!r} is locked")

    monkeypatch.setattr(findings_migrate, "acquire_lock", fake_acquire_lock)

    report = findings_migrate.migrate(tickets, dry_run=True)
    row = report["tickets"][0]
    assert row["status"] == "would-rewrite", row

    code = handback.main(["migrate", "--tickets-root", str(tickets), "--dry-run"])
    assert code == 0


def test_dry_run_reports_would_change_totals(tmp_path, monkeypatch, capsys):
    """Step-7, external review F-3: the dry-run summary and the `--json`
    `files_changed` said 0 even when files would be rewritten (that key
    only ever counts an ACTUAL rewrite). A `would_change` total (tickets
    and files) must be reported in dry-run mode instead."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old_a = support.old_independent(2)
    support.add_ticket(tickets, "KLC-999", {
        "spec-review-findings.json": json.dumps(old_a),
    })
    old_b = support.old_independent(1)
    support.add_ticket(tickets, "KLC-9991", {
        "spec-review-findings.json": json.dumps(old_b),
    })

    report = findings_migrate.migrate(tickets, dry_run=True)
    assert report["would_change_tickets"] == 2
    assert report["would_change_files"] == 2
    assert report["files_changed"] == 0

    def never_called(*a, **kw):
        raise AssertionError("a dry run must never write anything")

    monkeypatch.setattr(findings_migrate, "_migrate_one", never_called)
    report2 = findings_migrate.migrate(tickets, dry_run=True)
    assert report2["would_change_files"] == 2

    code = handback.main(["migrate", "--tickets-root", str(tickets), "--dry-run", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["would_change_tickets"] == 2
    assert out["would_change_files"] == 2
    assert code == 0

    code_text = handback.main(["migrate", "--tickets-root", str(tickets), "--dry-run"])
    text = capsys.readouterr().out
    assert code_text == 0
    assert "2 file(s) in 2 ticket(s) would change" in text
