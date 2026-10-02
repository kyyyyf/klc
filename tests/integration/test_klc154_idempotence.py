"""tests/integration/test_klc154_idempotence.py — KLC-154 step-1, AC-5: a
second run over an already-migrated corpus reports zero changed files and
leaves every file byte-identical; a straggler file added after a run is
picked up and migrated by the NEXT run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def test_second_run_over_migrated_corpus_changes_nothing(tmp_path, monkeypatch):
    """AC-5: `migrate` run a second time over an already-migrated corpus
    reports the ticket unchanged and leaves every file byte-identical."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(2)
    support.add_ticket(tickets, "KLC-920", {
        "spec-review.md": support.verdict_md(old, []),
        "spec-review-findings.json": json.dumps(old),
    })
    first = findings_migrate.migrate(tickets)
    assert first["tickets"][0]["status"] == "rewritten", first["tickets"][0]

    before = support.tree_hashes(tickets)
    second = findings_migrate.migrate(tickets)
    after = support.tree_hashes(tickets)

    assert second["tickets"][0]["status"] == "unchanged"
    assert second["files_changed"] == 0
    assert before == after


def test_straggler_added_after_a_run_is_migrated_by_the_next_run(tmp_path, monkeypatch):
    """A straggler old-shape file written to the tree AFTER one run is
    migrated by the next run, while the already-migrated ticket stays
    unchanged (E-7)."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-921", {
        "spec-review.md": support.verdict_md(old, []),
        "spec-review-findings.json": json.dumps(old),
    })
    first = findings_migrate.migrate(tickets)
    assert first["tickets"][0]["status"] == "rewritten", first["tickets"][0]

    straggler_old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-922", {
        "spec-review.md": support.verdict_md(straggler_old, []),
        "spec-review-findings.json": json.dumps(straggler_old),
    })

    second = findings_migrate.migrate(tickets)
    rows = {r["ticket"]: r for r in second["tickets"]}
    assert rows["KLC-921"]["status"] == "unchanged"
    assert rows["KLC-922"]["status"] == "rewritten", rows["KLC-922"]

    new_json = json.loads((tdir / "spec-review-findings.json").read_text(encoding="utf-8"))
    assert new_json
    assert all(not findings_migrate.is_old(r) for r in new_json)
