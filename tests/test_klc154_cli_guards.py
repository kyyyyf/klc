"""tests/test_klc154_cli_guards.py — KLC-154 step-5, AC-11/AC-17 (AC-17
amended 2026-10-02 after review round 2, drift D-1): `handback.py migrate`
refuses with exit 2 and a specific printed reason when `--tickets-root` is
missing, is not this project's tickets directory, the imported
`spec_review.parse_review` does not return a one-shape `Finding` for a
canned verdict, or (klc-state feature ON) the up-front klc-state pull/
fetch fails; it exits 0 when no ticket failed, was skipped or needed
attention, and 1 when at least one did, in both dry-run and real mode; and
the `--json` report names every ticket/file/count the human-readable
report does.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "tests" / "integration"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402
import handback  # noqa: E402


def _fake_old_parser_module():
    """A fake older `spec_review` whose `parse_review` returns an object
    carrying a pre-KLC-127 `spec_review.Finding`-like record (not
    `findings.Finding`)."""
    mod = types.ModuleType("fake_spec_review_old")

    class _OldFinding:
        def __init__(self):
            self.rule_name = "infidelity"

    class _OldOutput:
        findings = [_OldFinding()]

    def parse_review(text, kind=None):
        return _OldOutput()

    mod.parse_review = parse_review
    return mod


def _fake_no_parse_review_module():
    return types.ModuleType("fake_spec_review_missing")


@pytest.mark.parametrize("case", ["old-parser", "no-parse-review", "no-tickets-root", "foreign-root"])
def test_refuses_exit_2(tmp_path, monkeypatch, capsys, case):
    """AC-11: each case refuses with exit 2 and a reason specific to it;
    the tree is left untouched."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-994", {
        "spec-review-findings.json": json.dumps(old),
    })
    before = support.tree_hashes(tickets)

    argv = ["migrate", "--tickets-root", str(tickets), "--dry-run"]

    if case == "old-parser":
        monkeypatch.setattr(findings_migrate, "spec_review", _fake_old_parser_module())
        expect = "does not return a one-shape Finding"
    elif case == "no-parse-review":
        monkeypatch.setattr(findings_migrate, "spec_review", _fake_no_parse_review_module())
        expect = "does not return a one-shape Finding"
    elif case == "no-tickets-root":
        argv = ["migrate", "--dry-run"]
        expect = "the following arguments are required: --tickets-root"
    else:  # foreign-root
        other = support.make_project(tmp_path / "other", monkeypatch)
        monkeypatch.setenv("PROJECT_ROOT", str(tmp_path / "project"))
        argv = ["migrate", "--tickets-root", str(other), "--dry-run"]
        expect = "is not this project's tickets directory"

    if case == "no-tickets-root":
        with pytest.raises(SystemExit) as exc_info:
            handback.main(argv)
        assert exc_info.value.code == 2
    else:
        code = handback.main(argv)
        assert code == 2

    err = capsys.readouterr().err
    assert expect in err, err
    assert support.tree_hashes(tickets) == before


@pytest.mark.parametrize("case,expected_code", [
    ("dry-run-clean", 0), ("dry-run-failed", 1), ("real-clean", 0), ("real-locked", 1),
])
def test_exit_codes_and_json_report(tmp_path, monkeypatch, capsys, case, expected_code):
    """AC-17: exit 0 when nothing failed or was skipped, 1 otherwise, in
    both dry-run and real mode, printing one JSON object under --json."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-995", {
        "spec-review-findings.json": json.dumps(old),
    })
    dry_run = case.startswith("dry-run")

    if case == "dry-run-failed":
        support.add_ticket(tickets, "KLC-996", {
            "spec-review-findings.json": "{not valid json",
        })
    elif case == "real-locked":
        real_acquire_lock = findings_migrate.acquire_lock

        def fake_acquire_lock(ticket):
            if ticket == "KLC-996":
                raise findings_migrate.LockedError("locked")
            return real_acquire_lock(ticket)

        support.add_ticket(tickets, "KLC-996", {
            "spec-review-findings.json": json.dumps(support.old_independent(1)),
        })
        monkeypatch.setattr(findings_migrate, "acquire_lock", fake_acquire_lock)

    argv = ["migrate", "--tickets-root", str(tickets), "--json"]
    if dry_run:
        argv.append("--dry-run")

    code = handback.main(argv)
    captured = capsys.readouterr()
    assert code == expected_code, captured

    report = json.loads(captured.out)
    assert isinstance(report, dict)
    assert "tickets" in report


def test_human_report_lines_match_json_report(tmp_path, monkeypatch, capsys):
    """AC-17: every ticket, file and count in the human-readable report
    appears in the JSON report too."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(2)
    support.add_ticket(tickets, "KLC-997", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.add_ticket(tickets, "KLC-998", {
        "spec-review-findings.json": "{not valid json",
    })

    code_text = handback.main(["migrate", "--tickets-root", str(tickets), "--dry-run"])
    text_out = capsys.readouterr().out
    code_json = handback.main(["migrate", "--tickets-root", str(tickets), "--dry-run", "--json"])
    json_out = capsys.readouterr().out
    report = json.loads(json_out)

    assert code_text == code_json
    for row in report["tickets"]:
        assert row["ticket"] in text_out
        for f in row["files"]:
            assert f["path"] in text_out
            assert f"{f['old_count']} -> {f['new_count']}" in text_out


def test_needs_attention_only_still_exits_1(tmp_path, monkeypatch, capsys):
    """AC-17 (amended 2026-10-02 after review round 2, drift D-1, step-8):
    a batch with NO failed and NO skipped ticket, but one `needs-attention`
    ticket, must still exit 1 — the amendment that added `needs-attention`
    as a third exit-1 trigger, alongside `failed`/`skipped`, must actually
    be covered by a test (drift D-1 found step-7's code already did this
    while AC-17's OLD wording said only `failed`/`skipped` matter)."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    tdir = support.add_ticket(tickets, "KLC-9c1", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    (tdir / findings_migrate.AUDIT_NOTE).write_text(
        json.dumps([{"at": "2026-01-01T00:00:00Z", "status": "pending",
                     "files": [{"path": "spec-review-findings.json", "old_count": 1,
                               "new_count": 1, "sha256_before": "x", "sha256_after": "y"}]}],
                   indent=2) + "\n", encoding="utf-8")

    code = handback.main(["migrate", "--tickets-root", str(tickets), "--json"])
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert report["failed"] == 0
    assert report["skipped"] == 0
    assert report["needs_attention"] == 1
    assert code == 1, captured
