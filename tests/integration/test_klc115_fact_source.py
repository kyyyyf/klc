"""KLC-115 step-6: FACT src must name project code, graduated so no in-flight
ticket breaks (AC-13, plus the F-3/D-203 revision-2 addendum).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import consistency_check  # noqa: E402
import items_verify  # noqa: E402


def _make_ticket(tmp_path, ticket, created, spec_fact_header, extra_attrs=""):
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:work",
        "track": "M", "created": created,
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        f"---\nticket: {ticket}\nkind: tech\n---\n\n"
        f"## Goals\n- do the thing\n\n"
        f"> [!FACT {spec_fact_header}]{extra_attrs}\n"
        f"> a claim about the codebase\n", encoding="utf-8")
    return ticket_dir


def test_fact_src_pointing_at_ticket_artifact_or_missing_file_fails_consistency_check(
        tmp_path, monkeypatch):
    """Enforced half (a ticket created on/after the epoch, D-203): a FACT
    whose src names no real project code fails consistency."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_ticket(tmp_path, "KLC-FS01", "2026-09-20",
                "F-001] src=meta.json verified=2026-01-01")
    errs = consistency_check.check_ticket("KLC-FS01")
    assert any("src must name a project code or config file" in e for e in errs), errs


def test_fact_src_pointing_at_real_project_code_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / "core" / "skills").mkdir(parents=True)
    (tmp_path / "core" / "skills" / "settings.py").write_text("# real code\n", encoding="utf-8")
    _make_ticket(tmp_path, "KLC-FS02", "2026-09-20",
                "F-001] src=core/skills/settings.py:42 verified=2026-01-01")
    errs = consistency_check.check_ticket("KLC-FS02")
    assert not any("src must name a project code or config file" in e for e in errs), errs


def test_pre_epoch_ticket_without_evidence_read_warns_instead_of_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_ticket(tmp_path, "KLC-FS03", "2026-09-17",   # one day BEFORE the epoch
                "F-001] src=core/skills/artefacts.py:175-176, core/skills/artefacts.py:245 "
                "verified=2026-01-01")
    warnings: list[str] = []
    errs = consistency_check.check_ticket("KLC-FS03", warnings=warnings)
    assert not any("src must name a project code or config file" in e for e in errs), errs
    assert any("F-001" in w and "src must name" in w for w in warnings), warnings


def test_ticket_created_after_the_epoch_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_ticket(tmp_path, "KLC-FS04", "2026-09-18",   # the epoch day itself
                "F-001] src=core/skills/artefacts.py:175-176, core/skills/artefacts.py:245 "
                "verified=2026-01-01")
    errs = consistency_check.check_ticket("KLC-FS04")
    assert any("F-001" in e and "src must name a project code or config file" in e
              for e in errs), errs


def test_evidence_read_item_blocks_regardless_of_ticket_age(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _make_ticket(tmp_path, "KLC-FS05", "2020-01-01",   # long before the epoch
                "F-001] src=meta.json evidence=read verified=2026-01-01")
    errs = consistency_check.check_ticket("KLC-FS05")
    assert any("F-001" in e and "src must name a project code or config file" in e
              for e in errs), errs


def test_missing_or_unparseable_created_date_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket_dir = tmp_path / ".klc" / "tickets" / "KLC-FS06"
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": "KLC-FS06", "kind": "tech", "phase": "build:work", "track": "M",
        # no "created" key at all
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        "---\nticket: KLC-FS06\nkind: tech\n---\n\n## Goals\n- do the thing\n\n"
        "> [!FACT F-001] src=meta.json verified=2026-01-01\n"
        "> a claim about the codebase\n", encoding="utf-8")
    warnings: list[str] = []
    errs = consistency_check.check_ticket("KLC-FS06", warnings=warnings)
    assert not any("src must name a project code or config file" in e for e in errs), errs
    assert any("F-001" in w for w in warnings), warnings


def test_superseded_snapshot_artifacts_are_out_of_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket_dir = _make_ticket(tmp_path, "KLC-FS07", "2026-09-20",
                              "F-001] src=core/skills/settings.py:1 verified=2026-01-01")
    snap_dir = ticket_dir / "_superseded" / "20260101T000000Z"
    snap_dir.mkdir(parents=True)
    (snap_dir / "spec.md").write_text(
        "> [!FACT F-002] src=meta.json verified=2026-01-01\n"
        "> a frozen historical claim\n", encoding="utf-8")
    errs = consistency_check.check_ticket("KLC-FS07")
    assert not any("F-002" in e for e in errs), errs


def _live_ticket_dirs():
    tickets_dir = FRAMEWORK_ROOT / ".klc" / "tickets"
    if not tickets_dir.exists():
        return []
    return sorted(p for p in tickets_dir.glob("*")
                 if p.is_dir() and p.name != "archive" and (p / "meta.json").exists())


def test_no_live_ticket_blocks_unless_opted_in_or_created_after_the_epoch():
    """F-3's live-data guard: over every ticket under .klc/tickets/, a blocking
    FACT-source finding must belong to an opted-in item or a ticket created on
    or after the epoch — asserted as a predicate, not a fixed count, so it
    stays true as tickets are created and archived (and stays the standing
    proof that KLC-118's mid-build commits keep passing the pre-commit hook)."""
    line_re = re.compile(r": (\S+) in (\S+): src must name a project code or config file")
    for ticket_dir in _live_ticket_dirs():
        ticket = ticket_dir.name
        try:
            meta = json.loads((ticket_dir / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        errs = consistency_check.check_ticket(ticket)
        fact_errs = [e for e in errs if "src must name a project code or config file" in e]
        if not fact_errs:
            continue
        items_by_key = {}
        for item in items_verify.iter_facts(ticket_dir):
            try:
                rel = str(item.file.relative_to(ticket_dir)).replace("\\", "/")
            except ValueError:
                continue
            items_by_key[(item.id, rel)] = item
        for e in fact_errs:
            m = line_re.search(e)
            assert m, e
            key = (m.group(1), m.group(2))
            item = items_by_key.get(key)
            assert item is not None, e
            assert items_verify.fact_source_enforced(item, meta), (
                f"{ticket}/{key} would block although it predates the rule "
                f"and is not opted in: {e}")
