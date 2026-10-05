#!/usr/bin/env python3
"""KLC-117 step-7 — AC-15/AC-16: `klc migrate-notes`, idempotent and archive-aware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

import migrate_notes  # noqa: E402


def _seed(tmp_path: Path, ticket: str, *, note: str, phase: str = "build:ack-needed",
         archived: bool = False) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature",
        "phase": "archived" if archived else phase,
        "phase_history": [
            {"phase": "build:ack-needed", "started_at": "2026-01-01T00:00:00Z",
             "finished_at": "2026-01-01T00:00:01Z", "event": "manual-completion",
             "note": note},
        ],
        "track": "M", "affected_modules": ["core/skills"],
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return tdir / "meta.json"


_LONG_NOTE = "artifacts detected by phase_completion.py; " + "; ".join(
    f"ac-coverage[weak]: AC-{n} has an implemented test but its assertion looks weak"
    for n in range(1, 13)
)


def test_migration_truncates_overlong_notes_with_pointer_and_audit_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert len(_LONG_NOTE) > 200
    mp = _seed(tmp_path, "KLC-M01", note=_LONG_NOTE)

    result = migrate_notes.migrate_ticket("KLC-M01")
    assert result["migrated"] == 1

    meta = json.loads(mp.read_text())
    entry = meta["phase_history"][0]
    assert len(entry["note"]) <= 200
    assert "see build/ack-advisories.json" in entry["note"]
    # exactly one audit entry appended
    audit = [e for e in meta["phase_history"] if e.get("event") == "note-migration"]
    assert len(audit) == 1
    # phase/event/timestamps/pick of the migrated entry itself are untouched (C-005)
    assert entry["phase"] == "build:ack-needed"
    assert entry["event"] == "manual-completion"
    assert entry["started_at"] == "2026-01-01T00:00:00Z"
    assert entry["finished_at"] == "2026-01-01T00:00:01Z"


def test_migration_leaves_short_notes_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-M02", note="a short note")
    before = mp.read_text()

    result = migrate_notes.migrate_ticket("KLC-M02")
    assert result["migrated"] == 0

    after = mp.read_text()
    before_meta = json.loads(before)
    after_meta = json.loads(after)
    assert before_meta["phase_history"] == after_meta["phase_history"]


def test_migration_idempotent_on_second_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-M03", note=_LONG_NOTE)

    migrate_notes.migrate_ticket("KLC-M03")
    after_first = mp.read_text()

    result2 = migrate_notes.migrate_ticket("KLC-M03")
    after_second = mp.read_text()

    assert after_first == after_second
    assert result2["migrated"] == 0
    meta = json.loads(after_second)
    audit = [e for e in meta["phase_history"] if e.get("event") == "note-migration"]
    assert len(audit) == 1  # no new audit entry


def test_migration_covers_archived_tickets_too(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-M04", note=_LONG_NOTE, archived=True)

    result = migrate_notes.migrate_ticket("KLC-M04")
    assert result["migrated"] == 1

    meta = json.loads(mp.read_text())
    assert meta["phase"] == "archived"  # untouched
    entry = meta["phase_history"][0]
    assert len(entry["note"]) <= 200


def test_audit_entry_uses_a_bare_ts_field_not_started_finished_at(tmp_path, monkeypatch):
    """review-fix (HIGH, AC-15): the note-migration audit entry must be shaped
    like retrack.py/scope_fix.py's audit entries — a bare `ts`, never
    `started_at`/`finished_at` — so metrics._ct()'s cycle-time computation
    (which reads those two keys unconditionally from every phase_history
    entry) is not silently corrupted by the migration's own run time."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _seed(tmp_path, "KLC-M05", note=_LONG_NOTE)

    result = migrate_notes.migrate_ticket("KLC-M05")
    assert result["migrated"] == 1

    meta = json.loads(mp.read_text())
    audit = [e for e in meta["phase_history"] if e.get("event") == "note-migration"]
    assert len(audit) == 1
    assert "ts" in audit[0]
    assert "started_at" not in audit[0]
    assert "finished_at" not in audit[0]


def test_migrating_an_archived_ticket_does_not_change_its_metrics_cycle_time(
        tmp_path, monkeypatch):
    """review-fix (HIGH, AC-15): a real 2-day cycle (start day 1, archived day
    3) must report the SAME cycle_time_sec_median via the real
    `metrics.cmd_rollup` pipeline before and after migrate_ticket() runs over
    it. Before the fix, the migration's `started_at`/`finished_at`-carrying
    audit entry became the new lifecycle "end", reporting ~200 days instead
    of 2."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import argparse
    import metrics as _metrics

    ticket = "KLC-M06"
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "archived",
        "track": "M", "affected_modules": ["core/skills"],
        "phase_history": [
            {"phase": "intake:work", "started_at": "2026-01-01T00:00:00Z",
             "finished_at": "2026-01-01T00:00:01Z", "event": "manual-completion",
             "note": _LONG_NOTE},
            {"phase": "archived", "started_at": "2026-01-03T00:00:00Z",
             "finished_at": "2026-01-03T00:00:00Z", "event": "manual-completion",
             "note": "done"},
        ],
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    knowledge_dir = tmp_path / ".klc" / "knowledge"
    knowledge_dir.mkdir(parents=True)
    out_path = knowledge_dir / "process-metrics.json"

    _metrics.cmd_rollup(argparse.Namespace(output=None))
    before = json.loads(out_path.read_text())["per_track"]["M"]["cycle_time_sec_median"]
    assert before == 2 * 24 * 3600.0  # exactly the real 2-day cycle

    result = migrate_notes.migrate_ticket(ticket)
    assert result["migrated"] == 1

    _metrics.cmd_rollup(argparse.Namespace(output=None))
    after = json.loads(out_path.read_text())["per_track"]["M"]["cycle_time_sec_median"]
    assert after == before, (
        f"migration changed the ticket's cycle time: {before} -> {after}")


def test_dry_run_reports_real_counts_under_feature_on_simulation(tmp_path, monkeypatch):
    """review-fix (HIGH, AC-15): under a feature-ON (multi-user) deployment, a
    `--dry-run` writes nothing, so `state_tx`'s exit-side
    `commit_and_push_cas_subtree` sees a byte-identical subtree and raises
    `NothingToCommitError` — which migrate_ticket's own except-clause used to
    catch and turn into `{"migrated": 0, "skipped": "no-op"}`, discarding the
    real, correctly-computed counts. `--dry-run` must never enter `state_tx`
    at all. Simulated here with a stubbed `state_tx.state_tx` that raises
    immediately if ever entered — if `--dry-run` still routes through it,
    this test reproduces the exact discard bug; the fix must never call it."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import contextlib
    import state_sync as _state_sync

    mp = _seed(tmp_path, "KLC-M07", note=_LONG_NOTE)

    @contextlib.contextmanager
    def _stub_state_tx_always_raises(ticket, msg):
        raise _state_sync.NothingToCommitError("nothing to commit (stub)")
        yield  # pragma: no cover — unreachable, keeps this a generator

    monkeypatch.setattr(migrate_notes.state_tx, "state_tx",
                        _stub_state_tx_always_raises)

    def _boom_write_meta(*a, **k):
        raise AssertionError("--dry-run must write nothing")

    monkeypatch.setattr(migrate_notes._lc, "write_meta", _boom_write_meta)

    result = migrate_notes.migrate_ticket("KLC-M07", dry_run=True)
    assert result["migrated"] == 1
    assert result["reclaimed"] > 0
    assert "skipped" not in result

    # nothing was written — the file is byte-identical to what _seed wrote.
    meta = json.loads(mp.read_text())
    assert not any(e.get("event") == "note-migration" for e in meta["phase_history"])
