#!/usr/bin/env python3
"""tests/integration/test_klc127_fixture_redaction.py — KLC-127 step-6,
AC-30 (replay half): the committed replay fixtures under
`tests/fixtures/klc127-replay/` are complete, in the one Finding shape, and
carry none of the internal identifiers the KLC-133 fixture redaction gate
(`tests/integration/_klc133_support.forbidden_hits`, moved here from
`test_klc133_fixtures.py` in this step) forbids.

Hostile-input-first (impl-plan.md, "Rules that hold across every step"):
`test_redaction_gate_bites_on_a_seeded_leak` proves the gate itself still
bites before the fixture-completeness tests below trust it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc133_support as support
from _klc133_support import (  # noqa: E402
    FORBIDDEN_PATTERNS,
    PRIVATE_TERM_LABEL,
    REDACT_TERMS_ENV,
    forbidden_hits,
)

import handback  # noqa: E402

REPLAY = Path(__file__).resolve().parents[1] / "fixtures" / "klc127-replay"
TICKETS = ("KLC-133", "KLC-137", "KLC-139")


def test_redaction_gate_bites_on_a_seeded_leak(monkeypatch) -> None:
    """AC-1: the shared gate still fires on a seeded leak before any fixture
    trusts it — a scratch path, an injected private term (uppercase, via a
    comma-padded `KLC_REDACT_TERMS`) and a decorator '@property' are three
    independent hits, not one merged hit, and the label never echoes the
    term that matched."""
    monkeypatch.setenv(REDACT_TERMS_ENV, ",ZYXQUORP,, ")
    leak = "See /tmp/scratch/file.py -- zyxquorp uses the @property decorator here."
    hits = forbidden_hits(leak)
    assert len(hits) == 3
    assert "a /tmp/ path" in hits
    assert PRIVATE_TERM_LABEL in hits
    assert "an '@' (e-mail-shaped text)" in hits
    assert "zyxquorp" not in " ".join(hits).lower()


def test_private_terms_file_is_read_and_applied(monkeypatch, tmp_path) -> None:
    """AC-1: a term from the untracked terms file (blank lines and `#`
    comments ignored) is applied the same way as one from the env var."""
    monkeypatch.delenv(REDACT_TERMS_ENV, raising=False)
    terms_file = tmp_path / "redaction-terms.txt"
    terms_file.write_text("\n# a comment\nzyxquorp\n\n", encoding="utf-8")
    monkeypatch.setattr(support, "REDACTION_TERMS_FILE", terms_file)
    hits = forbidden_hits("plain text mentioning zyxquorp only")
    assert hits == [PRIVATE_TERM_LABEL]


def test_generic_patterns_hold_without_private_terms(monkeypatch, tmp_path) -> None:
    """AC-2: with `KLC_REDACT_TERMS` unset and the terms-file path absent,
    the generic patterns still fire and no error is raised."""
    monkeypatch.delenv(REDACT_TERMS_ENV, raising=False)
    monkeypatch.setattr(support, "REDACTION_TERMS_FILE", tmp_path / "no-such-file.txt")
    leak = (
        "See /tmp/scratch and /home/user -- msg_ABC123 toolu_0XYZ "
        "11111111-1111-1111-1111-111111111111 \"signature\": here @nope"
    )
    hits = forbidden_hits(leak)
    assert PRIVATE_TERM_LABEL not in hits
    assert "a /tmp/ path" in hits
    assert "a /home/ path" in hits
    assert "a real msg_<id>" in hits
    assert "a real toolu_0<id>" in hits
    assert "a UUID" in hits
    assert "the word 'signature' outside the redacted placeholder line" in hits
    assert "an '@' (e-mail-shaped text)" in hits


def test_tracked_file_scan_bites_on_a_planted_term(tmp_path) -> None:
    """AC-3: the tracked-file scan itself is proven to bite — a planted term
    in a regular file is reported, and the same planted term under `.klc/`
    (the live ticket-state directory, never tracked on main) is skipped."""
    (tmp_path / "leaky.py").write_text("term = 'zyxquorp'\n", encoding="utf-8")
    ignored = tmp_path / ".klc"
    ignored.mkdir()
    (ignored / "notes.md").write_text("zyxquorp\n", encoding="utf-8")
    hits = support.tracked_files_with_private_terms(tmp_path, ("zyxquorp",))
    assert hits == ["leaky.py"]


def test_tracked_files_carry_no_private_term(monkeypatch) -> None:
    """AC-3: across all tracked files of the branch, none of the operator's
    real configured private terms appear — the same check as the operator's
    `git grep -i -F -f .klc/config/redaction-terms.txt`, run as an autotest;
    vacuous (and still green) when no terms are configured."""
    monkeypatch.delenv(REDACT_TERMS_ENV, raising=False)
    terms = support.private_redaction_terms()
    hits = support.tracked_files_with_private_terms(support.FW_ROOT, terms)
    assert hits == []


@pytest.mark.parametrize("ticket", TICKETS)
def test_replay_fixture_ticket_is_complete_and_one_shape(ticket: str) -> None:
    """AC-30/AC-21: every replay ticket has both findings files and a
    pairs.json, and every finding in every file is in the one Finding shape
    (validate_findings, stored mode)."""
    pairs_path = REPLAY / f"{ticket}-pairs.json"
    assert pairs_path.is_file(), f"{ticket}: pairs.json missing"
    pairs = json.loads(pairs_path.read_text(encoding="utf-8"))
    assert isinstance(pairs["true_pairs"], list) and pairs["true_pairs"]
    assert isinstance(pairs["pooled_count"], int)
    for kind in ("code-review", "external-review"):
        findings_path = REPLAY / f"{ticket}-{kind}-findings.json"
        assert findings_path.is_file(), f"{ticket}: {kind}-findings.json missing"
        items = json.loads(findings_path.read_text(encoding="utf-8"))
        assert isinstance(items, list) and items
        errors = handback.validate_findings(kind, items)
        assert errors == [], f"{ticket}/{kind}: {errors}"


def test_klc127_replay_fixtures_pass_the_klc133_redaction_gate() -> None:
    """AC-30: every committed replay fixture (findings files, pairs.json and
    the README) carries none of the KLC-133 gate's forbidden identifiers."""
    for path in sorted(REPLAY.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        hits = forbidden_hits(text)
        assert hits == [], f"{path.relative_to(REPLAY)}: found {hits}"


def test_replay_readme_names_origin_redactions_and_scores() -> None:
    """AC-30: the replay README names each file's origin, records each
    redaction performed, and records the recomputed similarity of every true
    and near-miss pair (A-102's margin-survives claim, in writing)."""
    readme = (REPLAY / "README.md").read_text(encoding="utf-8")
    for ticket in TICKETS:
        assert ticket in readme
    assert "Redactions" in readme
    assert "similarity" in readme.lower()
    assert "0.15" in readme  # the configured min_similarity, named not hard-assumed
