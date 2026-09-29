"""Tests for drift_review.py — the FOURTH binding of KLC-084's ReviewKind seam
(DRIFT_CHECK, KLC-099). Mirrors test_klc094_implplan_review: the descriptor carries the
drift vocabulary and the thin consume delegates to the generic seam (no fork)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# KLC-136 AC-3 (F-012 group (b), read-side — distinct from step-1's AC-5
# write-side fix in this same file): redirect PROJECT_ROOT to an empty
# per-test project for every test in this file.
pytestmark = pytest.mark.usefixtures("hermetic_project_root")


# ------------------------------------------------ step-1: descriptor + thin consume

def test_drift_check_descriptor_exposed():
    """AC-1: drift_review exposes a DRIFT_CHECK ReviewKind with the drift vocabulary."""
    import drift_review
    dc = drift_review.DRIFT_CHECK
    assert dc.name == "drift"
    assert dc.output_file == "drift-review.md"
    assert set(dc.finding_categories) == {"decision-violation", "unrecorded-decision", "spec-drift"}
    assert set(dc.decision_topics) == {"intentional-deviation", "decision-supersession"}


def test_consume_delegates_to_seam(monkeypatch, tmp_path):
    """AC-2: drift_review.consume delegates to spec_review.consume with kind=DRIFT_CHECK."""
    import drift_review
    import spec_review
    captured = {}

    def _fake(ticket_dir, track, signals=None, kind=None, persist=True):
        captured["kind"] = kind
        captured["persist"] = persist
        return ([], [])

    monkeypatch.setattr(spec_review, "consume", _fake)
    drift_review.consume(tmp_path, "S", persist=False)
    assert captured["kind"] is drift_review.DRIFT_CHECK
    assert captured["persist"] is False


def test_validate_accepts_drift_rejects_spec_category():
    """AC-3: validate accepts a DRIFT_CHECK category and rejects a spec-only one under the kind."""
    import drift_review
    import spec_review
    good = spec_review.ReviewOutput(
        findings=[spec_review.Finding("F-1", "decision-violation", "medium", "d")])
    assert spec_review.validate(good, kind=drift_review.DRIFT_CHECK) == []
    bad = spec_review.ReviewOutput(
        findings=[spec_review.Finding("F-1", "infidelity", "medium", "d")])  # spec-only
    assert spec_review.validate(bad, kind=drift_review.DRIFT_CHECK) != []


# --------------------------------------- step-2: reviewer prompt + review.md spawn-doc

def test_prompt_categories_match_descriptor():
    """AC-6: the drift-reviewer prompt enumerates exactly the DRIFT_CHECK vocabulary
    (closed-world honesty — a fabricated/absent category fails this)."""
    import drift_review
    prompt = (_FW_ROOT / "core" / "agents" / "drift-reviewer.md").read_text(encoding="utf-8")
    for cat in drift_review.DRIFT_CHECK.finding_categories:
        assert cat in prompt, f"finding category {cat!r} not documented in the prompt"
    for topic in drift_review.DRIFT_CHECK.decision_topics:
        assert topic in prompt, f"decision topic {topic!r} not documented in the prompt"
    for spec_only in ("infidelity", "code-contradiction", "untestable-ac"):
        assert spec_only not in prompt  # spec-only categories must not leak in
    # codex P2: the prompt must require writing the verdict INTO the ticket directory,
    # else consume (reading klc_ticket_meta_file(ticket).parent) treats it as missing.
    assert ".klc/tickets" in prompt


def test_review_documents_drift_spawn():
    """AC-7: review.md documents spawning the fresh drift-reviewer (so drift-review.md
    is produced before the integrate ack consumes it — spec-review D-1)."""
    review = (_FW_ROOT / "core" / "agents" / "review.md").read_text(encoding="utf-8")
    assert "drift-reviewer" in review and "drift-review.md" in review and "fresh" in review


# --------------------------------------- step-3: consume wired at the integrate ack

def test_integrate_surfaces_drift_review_decisions(monkeypatch, tmp_path):
    """AC-4: the integrate ack advisory carries the drift-review outputs (surface-only).

    KLC-117: `_drift_review_advisories` now reads `drift_review.consume_records`
    (the record-shaped twin of `consume`) rather than `consume` itself. The ack's
    return value is now the aggregator's one-line summary; the actual record
    content is asserted from the persisted artifact (`persist=True`).
    """
    import phase_completion as pc
    import advisories as _adv_mod
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "M", "risk_tags": []})
    monkeypatch.setattr(pc, "_drift_advisories", lambda t, p, **_kw: [])  # isolate the 099 part
    monkeypatch.setattr(
        pc._drift_review, "consume_records",
        lambda td, track, sig=None, persist=True: (
            [{"source": "drift-review", "severity": "high", "code": "drift-review.decision",
              "message": "drift-review: 1 decision to confirm", "ref": ""}], []))
    ok, msg = pc._can_complete_generic("KLC-X", "integrate", persist=True)
    assert ok is True and msg
    envelope = _adv_mod.read("KLC-X", "integrate")
    assert envelope is not None
    assert any("drift-review: 1 decision to confirm" in r["message"]
              for r in envelope["records"])


def test_records_findings_only_on_persist(monkeypatch, tmp_path):
    """AC-5: persist threads through, and every write stays under tmp_path."""
    import phase_completion as pc
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    seen = []
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "M", "risk_tags": []})
    monkeypatch.setattr(pc, "_drift_advisories", lambda t, p, **_kw: [])
    monkeypatch.setattr(
        pc._drift_review, "consume_records",
        lambda td, track, sig=None, persist=True: (seen.append(persist) or ([], [])))
    pc._can_complete_generic("KLC-X", "integrate", persist=False)
    pc._can_complete_generic("KLC-X", "integrate", persist=True)
    assert seen == [False, True]
    assert (tmp_path / ".klc/tickets/KLC-X/integrate/ack-advisories.json").exists()


@pytest.mark.parametrize("live_index_state", ["stale"], indirect=True)
def test_verdict_unchanged_with_project_root_redirected(live_index_state, no_index_reads, monkeypatch):
    """AC-3: the persist=False call of test_records_findings_only_on_persist,
    repeated under a stand-in live index — never reads it."""
    import phase_completion as pc
    seen = []
    monkeypatch.setattr(pc._lc, "read_meta_ro", lambda t: {"track": "M", "risk_tags": []})
    monkeypatch.setattr(pc, "_drift_advisories", lambda t, p, **_kw: [])
    monkeypatch.setattr(
        pc._drift_review, "consume_records",
        lambda td, track, sig=None, persist=True: (seen.append(persist) or ([], [])))
    pc._can_complete_generic("KLC-X", "integrate", persist=False)
    assert seen == [False]
    assert no_index_reads() == []
