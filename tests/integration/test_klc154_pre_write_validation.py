"""tests/integration/test_klc154_pre_write_validation.py — KLC-154 step-1,
AC-8: every mapped finding list and every mapped verdict block is checked
(`handback.validate_findings`, stored mode) BEFORE the first byte is
written; `decisions_to_confirm` is carried through verbatim and never
re-validated; and an old-shape record carrying an unrecognised extra key
fails the ticket's plan before any write (D-006).
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
import spec_review  # noqa: E402


def test_migrated_findings_pass_stored_mode_validate_before_any_write(tmp_path, monkeypatch):
    """AC-8: every mapped list/block is checked (`handback.validate_findings`,
    stored mode) before the first `findings_migrate._write_bytes` call."""
    tickets = support.make_project(tmp_path, monkeypatch)
    support.add_ticket(tickets, "KLC-900", {
        "spec-review-findings.json": json.dumps(support.old_independent(2)),
    })

    order: list = []
    real_validate = handback.validate_findings
    real_write = findings_migrate._write_bytes

    def spy_validate(kind, items):
        order.append(("validate", kind))
        return real_validate(kind, items)

    def spy_write(path, data):
        order.append(("write", str(path)))
        return real_write(path, data)

    monkeypatch.setattr(handback, "validate_findings", spy_validate)
    monkeypatch.setattr(findings_migrate, "_write_bytes", spy_write)

    report = findings_migrate.migrate(tickets)

    assert report["tickets"][0]["status"] == "rewritten", report["tickets"][0]
    kinds_seen = [k for k, _ in order]
    assert "validate" in kinds_seen
    assert "write" in kinds_seen
    first_write = next(i for i, (k, _) in enumerate(order) if k == "write")
    assert all(k == "validate" for k, _ in order[:first_write])


def test_decisions_are_carried_verbatim_and_not_validated(tmp_path, monkeypatch):
    """AC-3/AC-8: `decisions_to_confirm` is carried through byte-for-byte as
    a parsed JSON value — never re-validated by `spec_review.validate` —
    even with a non-canonical key (`recommendation` instead of
    `recommended`) that `validate()` would refuse."""
    tickets = support.make_project(tmp_path, monkeypatch)
    decisions = [{"id": "D-1", "topic": "scope", "question": "q?",
                 "recommendation": "do it anyway"}]
    old = support.old_independent(1)
    text = support.verdict_md(old, decisions)
    tdir = support.add_ticket(tickets, "KLC-901", {"spec-review.md": text})

    def boom(*a, **kw):
        raise AssertionError("spec_review.validate must not run during migration")

    monkeypatch.setattr(spec_review, "validate", boom)

    report = findings_migrate.migrate(tickets)
    assert report["tickets"][0]["status"] == "rewritten", report["tickets"][0]

    new_text = (tdir / "spec-review.md").read_text(encoding="utf-8")
    span = findings_migrate._verdict_span(new_text)
    assert span is not None
    _, _, doc = span
    assert doc["decisions_to_confirm"] == decisions


def test_unknown_old_key_fails_the_ticket_before_any_write(tmp_path, monkeypatch):
    """D-006: an old-shape record carrying an unrecognised extra key fails
    the ticket's plan — before any write — instead of silently dropping or
    guessing at the key."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    old[0]["mystery_key"] = "???"
    raw = json.dumps(old)
    tdir = support.add_ticket(tickets, "KLC-902", {"spec-review-findings.json": raw})

    report = findings_migrate.migrate(tickets)

    row = report["tickets"][0]
    assert row["status"] == "failed"
    assert "mystery_key" in row["reason"]
    assert (tdir / "spec-review-findings.json").read_text(encoding="utf-8") == raw
