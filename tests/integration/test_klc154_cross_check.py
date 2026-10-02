"""tests/integration/test_klc154_cross_check.py — KLC-154 step-1, AC-9: for
each of the four independent kinds whose ticket holds both the `.md` and the
JSON file, the migrated derived JSON equals, as parsed JSON, the records
`record_findings(parse_review(migrated block))` returns — else the ticket is
listed failed and left untouched. A `.md`-only ticket gets no derived JSON
created at all.
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
import handback  # noqa: E402
import spec_review  # noqa: E402

_INDEP_FILES = {
    "spec": ("spec-review.md", "spec-review-findings.json"),
    "test-plan": ("test-plan-review.md", "test-plan-review-findings.json"),
    "impl-plan": ("impl-plan-review.md", "impl-plan-review-findings.json"),
    "drift": ("drift-review.md", "drift-review-findings.json"),
}


@pytest.mark.parametrize("kind", ["spec", "test-plan", "impl-plan", "drift"])
def test_md_and_json_cross_check_equal_for_each_independent_kind(tmp_path, monkeypatch, kind):
    """AC-9: the migrated `.md` verdict and the migrated derived JSON agree
    for every independent kind, even though the two old-shape inputs differ
    in the E-6 normalisation style: `ref` absent against `""`,
    `suggested_fix` absent against `""`, and upper-case against lower-case
    severity."""
    tickets = support.make_project(tmp_path, monkeypatch)
    output_file, json_file = _INDEP_FILES[kind]
    category = handback.KINDS[kind].rule_names[0]
    md_old = [{"id": "F-1", "category": category, "severity": "high",
              "detail": "the same underlying defect", "ref": "", "suggested_fix": None}]
    json_old = [{"id": "F-1", "category": category, "severity": "HIGH",
                "detail": "the same underlying defect"}]
    text = support.verdict_md(md_old, [])
    tdir = support.add_ticket(tickets, "KLC-910", {
        output_file: text, json_file: json.dumps(json_old),
    })

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "rewritten", row

    new_json = json.loads((tdir / json_file).read_text(encoding="utf-8"))
    new_text = (tdir / output_file).read_text(encoding="utf-8")
    binding = handback.KINDS[kind].binding
    derived = spec_review.record_findings(spec_review.parse_review(new_text, binding), None, binding)
    assert derived == new_json


def test_cross_check_mismatch_marks_ticket_failed_and_untouched(tmp_path, monkeypatch):
    """AC-9: when the migrated `.md` and the migrated JSON would disagree,
    the ticket is listed failed and both files are left byte-identical."""
    tickets = support.make_project(tmp_path, monkeypatch)
    md_old = [{"id": "F-1", "category": "infidelity", "severity": "high",
              "detail": "defect A"}]
    json_old = [{"id": "F-1", "category": "infidelity", "severity": "high",
                "detail": "a totally different defect"}]
    text = support.verdict_md(md_old, [])
    support.add_ticket(tickets, "KLC-911", {
        "spec-review.md": text,
        "spec-review-findings.json": json.dumps(json_old),
    })
    before = support.tree_hashes(tickets)

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "failed"
    assert support.tree_hashes(tickets) == before


def test_md_only_ticket_gets_no_derived_json(tmp_path, monkeypatch):
    """A ticket with only the `.md` verdict (no stored JSON for that kind)
    is rewritten in place, and no derived `<kind>-review-findings.json` is
    ever created (AC-2: the migration creates no file other than the audit
    note)."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    text = support.verdict_md(old, [])
    tdir = support.add_ticket(tickets, "KLC-912", {"spec-review.md": text})

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "rewritten", row
    assert not (tdir / "spec-review-findings.json").exists()
