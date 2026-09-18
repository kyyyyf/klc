"""KLC-115 step-3: track scaling for evidence_gate.check_evidence — off on
XS, surface-only on S, blocking on M/L with the meta.json override (AC-15).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import evidence_gate as eg  # noqa: E402


def _make_ticket(tmp_path, ticket, track, spec_acs, evidence_body="", meta_extra=None):
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": track,
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    meta.update(meta_extra or {})
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    spec_lines = ["---", f"ticket: {ticket}", "kind: feature", "---", "",
                 "## Acceptance Criteria"]
    for ac in spec_acs:
        spec_lines.append(f"- [ ] {ac}: subject · acts · object · when a thing happens")
    (ticket_dir / "spec.md").write_text("\n".join(spec_lines), encoding="utf-8")
    build_log = (f"---\nticket: {ticket}\nkind: build-log\n---\n\n"
                f"# Build log — {ticket}\n\n## Evidence\n\n{evidence_body}\n")
    (ticket_dir / "build-log.md").write_text(build_log, encoding="utf-8")
    return ticket_dir


def test_ac_without_entry_is_off_on_xs(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-TS01"
    _make_ticket(tmp_path, ticket, "XS", ["AC-1"])
    rep = eg.check_evidence(ticket, "XS", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason
    assert not rep.findings


def test_ac_without_entry_surfaces_on_s(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-TS02"
    _make_ticket(tmp_path, ticket, "S", ["AC-1"])
    rep = eg.check_evidence(ticket, "S", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason
    assert rep.surfaced
    assert "AC-1" in rep.surfaced[0].message


def test_meta_override_downgrades_m_block_to_advisory(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-TS03"
    _make_ticket(tmp_path, ticket, "M", ["AC-1"],
                meta_extra={"deferred_verify_evidence": True})
    rep = eg.check_evidence(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason
    assert rep.surfaced
    assert "AC-1" in rep.surfaced[0].message
