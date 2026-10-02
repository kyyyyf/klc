"""tests/integration/test_klc154_symlink_refused.py — KLC-154 step-7,
code-review F-1 (LOW): the atomic writer's `tmp.replace(path)` replaces
whatever directory entry sits at `path` — if a mapped findings file or
verdict `.md` were a symlink, a migration write would silently turn the
symlink into a plain file holding the new content, leaving the original
symlink target untouched elsewhere and the symlink itself gone.

Fixed by refusing (`PlanError`, so the ticket is listed `failed`, byte-
identical, BEFORE any write) a mapped path that is a symlink — in
`_read_list` (stored JSON) and in `plan_ticket`'s independent-kind `.md`
loop.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def test_symlinked_stored_findings_file_is_refused(tmp_path, monkeypatch):
    tickets = support.make_project(tmp_path, monkeypatch)
    real_target = tmp_path / "elsewhere.json"
    old = support.old_independent(1)
    real_target.write_text(json.dumps(old), encoding="utf-8")
    tdir = support.add_ticket(tickets, "KLC-9c1", {})
    link = tdir / "spec-review-findings.json"
    link.symlink_to(real_target)

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "failed", row
    assert "symlink" in row["reason"]
    assert link.is_symlink()
    assert real_target.read_text(encoding="utf-8") == json.dumps(old)


def test_symlinked_verdict_md_is_refused(tmp_path, monkeypatch):
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    real_target = tmp_path / "elsewhere.md"
    real_target.write_text(support.verdict_md(old, []), encoding="utf-8")
    tdir = support.add_ticket(tickets, "KLC-9c2", {})
    link = tdir / "spec-review.md"
    link.symlink_to(real_target)

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "failed", row
    assert "symlink" in row["reason"]
    assert link.is_symlink()
    assert real_target.read_text(encoding="utf-8") == support.verdict_md(old, [])
