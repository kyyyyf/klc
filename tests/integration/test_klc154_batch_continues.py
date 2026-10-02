"""tests/integration/test_klc154_batch_continues.py — KLC-154 step-1, AC-6:
one ticket's plan failing (invalid JSON, a record that fails the AC-8 check,
or an unexpected exception during planning) is listed failed with its
reason, and every other ticket still migrates (the per-ticket catch-all;
impl-plan-review F-2). Step-2 adds the `locked` case.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


@pytest.mark.parametrize("case", ["invalid-json", "fails-ac8", "unexpected-exception", "locked"])
def test_one_bad_ticket_is_skipped_others_proceed(tmp_path, monkeypatch, case):
    """AC-6: one malformed (or locked) ticket is listed failed/skipped with
    its reason; every other ticket still migrates."""
    tickets = support.make_project(tmp_path, monkeypatch)
    good_old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-930", {
        "spec-review-findings.json": json.dumps(good_old),
    })

    victim = "KLC-931"
    if case == "invalid-json":
        support.add_ticket(tickets, victim, {
            "spec-review-findings.json": "{not valid json",
        })
    elif case == "fails-ac8":
        bad = support.old_independent(1, severity="urgent")
        support.add_ticket(tickets, victim, {
            "spec-review-findings.json": json.dumps(bad),
        })
    elif case == "locked":
        bad = support.old_independent(1)
        support.add_ticket(tickets, victim, {
            "spec-review-findings.json": json.dumps(bad),
        })
        real_acquire_lock = findings_migrate.acquire_lock

        def fake_acquire_lock(ticket):
            if ticket == victim:
                raise findings_migrate.LockedError(f"ticket {ticket!r} is locked")
            return real_acquire_lock(ticket)

        monkeypatch.setattr(findings_migrate, "acquire_lock", fake_acquire_lock)
    else:
        bad = support.old_independent(1)
        bad[0]["id"] = "VICTIM-MARK"
        support.add_ticket(tickets, victim, {
            "spec-review-findings.json": json.dumps(bad),
        })
        real_map_findings = findings_migrate.map_findings

        def spy(items, kind, *, stamp=False):
            if items and isinstance(items[0], dict) and items[0].get("id") == "VICTIM-MARK":
                raise TypeError("boom for victim only")
            return real_map_findings(items, kind, stamp=stamp)

        monkeypatch.setattr(findings_migrate, "map_findings", spy)

    report = findings_migrate.migrate(tickets)
    rows = {r["ticket"]: r for r in report["tickets"]}

    assert rows["KLC-930"]["status"] == "rewritten", rows["KLC-930"]
    expected_status = "skipped" if case == "locked" else "failed"
    assert rows[victim]["status"] == expected_status, rows[victim]
    assert rows[victim]["reason"]
