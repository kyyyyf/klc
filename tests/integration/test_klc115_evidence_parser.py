"""KLC-115 step-2: core/skills/evidence_gate.py — one Evidence entry per
acceptance-criterion id, parsed in structure-only mode (AC-1, AC-2, AC-3, AC-17).
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import evidence_gate as eg  # noqa: E402


def _dedent(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def test_entry_declaring_two_ac_ids_covers_both():
    text = _dedent("""
        ### AC-1, AC-2 — both close together

        ```
        $ pytest tests/test_x.py -q
        2 passed in 0.10s
        ```
        """)
    by_ac, malformed = eg.parse_evidence(text, ["AC-1", "AC-2"])
    assert not malformed
    assert set(by_ac) == {"AC-1", "AC-2"}
    e1, e2 = by_ac["AC-1"], by_ac["AC-2"]
    assert e1 is e2  # the SAME entry object covers both ids
    assert e1.commands == ["pytest tests/test_x.py -q"]
    assert "2 passed in 0.10s" in e1.output
    assert e1.verdict == eg.PASS


def test_fence_with_no_command_line_is_not_a_valid_entry():
    text = _dedent("""
        ### AC-1 — no command line, just captured output

        ```
        2 passed in 0.10s
        ```
        """)
    by_ac, malformed = eg.parse_evidence(text, ["AC-1"])
    assert "AC-1" not in by_ac
    assert len(malformed) == 1


def test_entry_without_verdict_line_is_implicit_pass():
    text = _dedent("""
        ### AC-1 — no verdict line at all

        ```
        $ pytest tests/test_x.py -q
        1 passed in 0.05s
        ```
        """)
    by_ac, malformed = eg.parse_evidence(text, ["AC-1"])
    assert not malformed
    assert by_ac["AC-1"].verdict == eg.PASS


def test_deferred_entry_with_reason_is_well_formed():
    text = _dedent("""
        ### AC-1 — deferred with a real reason
        verdict: deferred(infrastructure gap — no staging environment)

        ```
        $ echo not run
        not run
        ```
        """)
    by_ac, malformed = eg.parse_evidence(text, ["AC-1"])
    assert not malformed
    entry = by_ac["AC-1"]
    assert entry.verdict == eg.DEFERRED
    assert entry.reason == "infrastructure gap — no staging environment"


def test_deferred_entry_without_reason_is_rejected():
    text = _dedent("""
        ### AC-1 — deferred with no reason
        verdict: deferred

        ```
        $ echo not run
        not run
        ```
        """)
    by_ac, malformed = eg.parse_evidence(text, ["AC-1"])
    assert "AC-1" not in by_ac
    assert len(malformed) == 1
    assert malformed[0].verdict == eg.MALFORMED


def test_entry_naming_unknown_ac_id_is_ignored():
    text = _dedent("""
        ### AC-99 — a renamed or removed acceptance criterion

        ```
        $ echo ok
        ok
        ```
        """)
    by_ac, malformed = eg.parse_evidence(text, ["AC-1"])
    assert by_ac == {}
    assert malformed == []


def test_prose_only_evidence_section_blocks_on_m(tmp_path, monkeypatch):
    """Fail-closed twin (bridges into AC-4's gate, step-3): a build-log whose
    Evidence section is pasted prose plus one unattributed fenced block, with
    a real spec.md declaring ACs, must BLOCK the build ack on track M — the
    NEW per-AC gate, not the old heading+fence check, which this exact shape
    would otherwise satisfy."""
    import json

    sys.path.insert(0, str(FRAMEWORK_ROOT))
    from core.skills.phase_completion import can_complete_build

    ticket = "KLC-EP01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(_dedent("""
        ---
        ticket: {ticket}
        kind: feature
        ---

        ## Acceptance Criteria
        - [ ] AC-1: subject · acts · object · when a thing happens
        """).format(ticket=ticket), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(_dedent("""
        ---
        ticket: {ticket}
        kind: build-log
        ---

        # Build log — {ticket}

        ## Evidence

        Verification was performed and everything looked correct.

        ```
        $ pytest tests/ -q
        5 passed
        ```
        """).format(ticket=ticket), encoding="utf-8")

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ok, msg = can_complete_build(ticket)
    assert not ok, f"expected False: prose-only Evidence must block on M, got {msg!r}"
    assert "AC-1" in msg, f"expected the uncovered AC named in the block message, got {msg!r}"
