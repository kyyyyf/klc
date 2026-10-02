"""tests/integration/test_klc154_state_tx.py — KLC-154 step-2, AC-10: a real
run against a git-backed `klc-state` checkout makes exactly one commit per
changed ticket, none for an unchanged one, and a write failure on a
ticket's second file leaves that ticket's subtree byte-identical and adds
no commit for it (feature ON). With the multi-user feature OFF, the same
write failure is restored by the migration's own `_apply` rollback, with no
git involved at all (D-007).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def test_one_commit_per_changed_ticket_and_rollback_on_write_failure(tmp_path, monkeypatch):
    """AC-10: exactly one `klc-state` commit per changed ticket, none for
    an unchanged one, and a write failure on the SECOND file of a third
    ticket leaves its subtree byte-identical with no commit for it."""
    tickets = support.make_project(tmp_path, monkeypatch)

    old_a = support.old_independent(1)
    support.add_ticket(tickets, "KLC-980", {
        "spec-review.md": support.verdict_md(old_a, []),
        "spec-review-findings.json": json.dumps(old_a),
    })
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    support.add_ticket(tickets, "KLC-981", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    old_c = support.old_independent(1)
    tdir_c = support.add_ticket(tickets, "KLC-982", {
        "spec-review.md": support.verdict_md(old_c, []),
        "spec-review-findings.json": json.dumps(old_c),
    })

    klc = tickets.parent
    support.seed_git_state(tmp_path)
    base_count = support.remote_commit_count(klc)

    before_c_md = (tdir_c / "spec-review.md").read_bytes()
    before_c_json = (tdir_c / "spec-review-findings.json").read_bytes()

    real_write = findings_migrate._write_bytes

    def flaky_write(path, data):
        if path.name == "spec-review.md" and path.parent.name == "KLC-982":
            raise OSError("simulated disk failure")
        return real_write(path, data)

    monkeypatch.setattr(findings_migrate, "_write_bytes", flaky_write)

    report = findings_migrate.migrate(tickets)
    rows = {r["ticket"]: r for r in report["tickets"]}

    assert rows["KLC-980"]["status"] == "rewritten", rows["KLC-980"]
    assert rows["KLC-981"]["status"] == "unchanged", rows["KLC-981"]
    assert rows["KLC-982"]["status"] == "skipped", rows["KLC-982"]

    after_count = support.remote_commit_count(klc)
    assert after_count == base_count + 1

    assert (tdir_c / "spec-review.md").read_bytes() == before_c_md
    assert (tdir_c / "spec-review-findings.json").read_bytes() == before_c_json


def test_feature_off_write_failure_restores_the_ticket_files(tmp_path, monkeypatch):
    """D-007: with the multi-user feature OFF (no git-backed `.klc` here),
    a write failure on the SECOND file still restores the FIRST file —
    `_apply`'s own restore-on-error, with no git involved."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-983", {
        "spec-review.md": support.verdict_md(old, []),
        "spec-review-findings.json": json.dumps(old),
    })
    before_md = (tdir / "spec-review.md").read_bytes()
    before_json = (tdir / "spec-review-findings.json").read_bytes()

    real_write = findings_migrate._write_bytes

    def flaky_write(path, data):
        if path.name == "spec-review.md":
            raise OSError("simulated disk failure")
        return real_write(path, data)

    monkeypatch.setattr(findings_migrate, "_write_bytes", flaky_write)

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "skipped", row
    assert (tdir / "spec-review.md").read_bytes() == before_md
    assert (tdir / "spec-review-findings.json").read_bytes() == before_json
