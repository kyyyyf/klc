#!/usr/bin/env python3
"""KLC-116 step-2 — AC-3/AC-4/AC-5 (the three companion rules), AC-6 (absence
warns and never blocks), and the revision-2 archival-scoping rows (F-2/D-202):
`provenance` reads a ticket's LIVE artefacts only, never a frozen
`_superseded/` snapshot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import provenance  # noqa: E402
import consistency_check  # noqa: E402


def _seed(tmp_path: Path, ticket: str, files: dict[str, str]) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:work",
        "phase_history": [], "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
        "affected_modules": ["core/skills"], "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for rel, body in files.items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tdir


# --- AC-3: observed / adjacent probe -----------------------------------------

def test_observed_without_adjacent_probe_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-910"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-1] evidence=observed\n"
            "> the button renders below the fold\n"
        )
    })
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["F-1"]
    assert findings[0].severity == "block"


def test_observed_with_adjacent_probe_in_quoted_body_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-911"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-1] evidence=observed\n"
            "> the button renders below the fold\n"
            "> ```\n"
            "> $ true\n"
            "> ok\n"
            "> ```\n"
        )
    })
    assert provenance.check_artefacts(ticket) == []


def test_observed_with_probe_immediately_following_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-912"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-1] evidence=observed\n"
            "> the button renders below the fold\n"
            "\n"
            "```\n"
            "$ true\n"
            "ok\n"
            "```\n"
        )
    })
    assert provenance.check_artefacts(ticket) == []


def test_observed_with_probe_separated_by_another_item_header_fails(tmp_path, monkeypatch):
    """Adjacency boundary (spec's own definition): a fence separated from the
    `observed` item by another item's header in between does NOT count."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-913"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-1] evidence=observed\n"
            "> the button renders below the fold\n"
            "\n"
            "> [!FACT F-2] unrelated claim\n"
            "> something else entirely\n"
            "\n"
            "```\n"
            "$ true\n"
            "ok\n"
            "```\n"
        )
    })
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["F-1"]


# --- AC-4: read / src shape and resolvability --------------------------------

def test_read_with_nonexistent_path_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-914"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!DECISION D-1] evidence=read src=core/skills/does-not-exist.py:5\n"
            "> use approach A\n"
        )
    })
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["D-1"]


def test_read_with_absent_src_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-915"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!DECISION D-1] evidence=read\n"
            "> use approach A\n"
        )
    })
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["D-1"]


def test_read_with_malformed_src_shape_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-916"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!DECISION D-1] evidence=read src=core/skills/items.py:1-5\n"
            "> use approach A\n"
        )
    })
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["D-1"]


def test_read_with_existing_path_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-917"
    real_file = tmp_path / "core" / "skills" / "widget.py"
    real_file.parent.mkdir(parents=True)
    real_file.write_text("# a real file under this fixture's project root\n", encoding="utf-8")
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!DECISION D-1] evidence=read src=core/skills/widget.py:1\n"
            "> use approach A\n"
        )
    })
    assert provenance.check_artefacts(ticket) == []


def test_read_pointing_at_ticket_artifact_path_is_accepted(tmp_path, monkeypatch):
    """C-002 boundary: a `read` src naming ANOTHER ticket's document resolves
    and passes here; whether that path is code vs. document is KLC-115's rule,
    not this gate's."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-918"
    other = tmp_path / ".klc" / "tickets" / "KLC-109" / "design"
    other.mkdir(parents=True)
    (other / "options.md").write_text("some other ticket's document\n", encoding="utf-8")
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!DECISION D-1] evidence=read src=.klc/tickets/KLC-109/design/options.md:1\n"
            "> use approach A\n"
        )
    })
    assert provenance.check_artefacts(ticket) == []


# --- AC-5: assumed / if-false -------------------------------------------------

def test_assumed_without_if_false_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-919"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!ASSUMPTION A-1] evidence=assumed\n"
            "> nobody will notice\n"
        )
    })
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["A-1"]


def test_assumed_with_if_false_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-920"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!ASSUMPTION A-1] evidence=assumed if-false=revisit-after-ship\n"
            "> nobody will notice\n"
        )
    })
    assert provenance.check_artefacts(ticket) == []


# --- AC-6: absence warns, never blocks ---------------------------------------

def test_missing_evidence_attribute_warns_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-921"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-1] owner=ek\n"
            "> a claim with no evidence attribute at all\n"
            "\n"
            "> [!FACT F-2] owner=ek\n"
            "> another claim with no evidence attribute\n"
        )
    })
    assert provenance.check_artefacts(ticket) == []
    warn = provenance.absence_warning(ticket)
    assert "design/options.md" in warn
    assert "2" in warn

    errs = consistency_check.check_ticket(ticket)
    assert errs == []
    captured = capsys.readouterr()
    assert "design/options.md" in captured.out


# --- revision 2 (F-2/D-202): archival scoping --------------------------------

def test_snapshot_items_are_not_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-922"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-1] evidence=observed\n"
            "> compliant claim\n"
            "> ```\n"
            "> $ true\n"
            "> ok\n"
            "> ```\n"
        ),
        "_superseded/20260101T000000Z/design/options.md": (
            "> [!FACT F-2] evidence=observed\n"
            "> a violating claim frozen in history, no probe anywhere\n"
        ),
    })
    assert provenance.check_artefacts(ticket) == []


def test_live_twin_of_a_snapshot_item_still_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-923"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-2] evidence=observed\n"
            "> a violating claim, now live, no probe anywhere\n"
        ),
        "_superseded/20260101T000000Z/design/options.md": (
            "> [!FACT F-2] evidence=observed\n"
            "> the same violating claim, frozen in history\n"
        ),
    })
    findings = provenance.check_artefacts(ticket)
    assert [f.item_id for f in findings] == ["F-2"]


def test_legacy_prompt_card_items_are_not_checked(tmp_path, monkeypatch):
    """review-fix (MEDIUM, D-303/Q-105): a stale legacy `_prompt*.md` card left
    behind in the ticket tree (pre-KLC-118 cards lived there; KLC-118 moved
    them to `.klc/scratch/`) must be excluded from provenance checks exactly
    like a frozen `_superseded/` snapshot — it is a leftover, never a live
    provenance item."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-924"
    _seed(tmp_path, ticket, {
        "design/options.md": (
            "> [!FACT F-1] evidence=observed\n"
            "> compliant claim\n"
            "> ```\n"
            "> $ true\n"
            "> ok\n"
            "> ```\n"
        ),
        "_prompt_step_1.md": (
            "> [!FACT F-3] evidence=observed\n"
            "> a violating claim in a stale legacy card, no probe anywhere\n"
        ),
    })
    assert provenance.check_artefacts(ticket) == []
