#!/usr/bin/env python3
"""KLC-117 step-4 — AC-17: the KLC-105 build ack note fixture shrinks.

Replays the real KLC-105 `build:ack-needed` producer output — twelve
textually-identical `ac-coverage[weak]` lines, one per AC, previously a
1496-byte joined note — through the new aggregator, and drives the real
manual-completion ack path so the WRITTEN phase-history note is measured, not
just the gate's return value.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "core" / "phases"))

import advisories  # noqa: E402
import ac_test_coverage as acov  # noqa: E402
import phase_completion as pc  # noqa: E402


def _twelve_weak_findings():
    return [
        acov.Finding(f"AC-{n}", acov.WEAK, acov.SURFACE,
                    f"AC-{n} has an implemented test but its assertion looks weak")
        for n in range(1, 13)
    ]


def _seed_ticket(tmp_path: Path, ticket: str) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:work",
        "phase_history": [], "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 1, "total": 5},
        "layer": "code", "affected_modules": ["core/skills"],
        "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "build-log.md").write_text(
        "# build log\n\n## Evidence\n\n```\n$ true\nok\n```\n", encoding="utf-8")
    (tdir / "impl-plan.md").write_text(
        f"# Implementation plan — {ticket}\n", encoding="utf-8")


def test_klc105_build_ack_note_shrinks_to_cap_with_all_12_records_present(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-105R"
    _seed_ticket(tmp_path, ticket)

    monkeypatch.setattr(pc, "_impl_plan_steps", lambda d: [])
    rep = acov.Report(track="M", findings=_twelve_weak_findings())
    monkeypatch.setattr(acov, "check", lambda *a, **k: rep)

    ok, summary = pc.can_complete_build(ticket)
    assert ok is True
    assert summary == (
        "0 high · 0 medium · 12 info — see "
        f".klc/tickets/{ticket}/build/ack-advisories.json"
    )

    envelope = advisories.read(ticket, "build")
    assert envelope is not None
    assert len(envelope["records"]) == 12
    assert all(r["severity"] == "info" for r in envelope["records"])

    import ack as ack_mod
    # The manual-completion transition writes the note and recurses into
    # ack-needed, which then needs a --pick (a separate, unrelated concern) —
    # rc may be non-zero for THAT reason, but the note is already persisted.
    ack_mod.run([ticket])
    meta = json.loads((tmp_path / ".klc" / "tickets" / ticket / "meta.json").read_text())
    note = meta["phase_history"][-1]["note"]
    assert len(note) <= advisories.NOTE_CAP
    assert note.endswith(summary)
