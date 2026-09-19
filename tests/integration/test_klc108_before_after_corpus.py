"""KLC-108 — AC-14/AC-15/AC-16: the BEFORE/AFTER corpus evidence.

Reads the recorded evidence report (`tests/fixtures/klc108/before_after_report.json`).

Review round 1 (HIGH #2 / drift-review F-1): the step-8 evidence compared a
full-110-ticket AFTER mean against the spec's stale 3-probe-ticket BEFORE pin
(0.1333) — not like-for-like, since AC-14 requires "a BEFORE run and an AFTER
run cover the same corpus" and AC-15 requires both means "measured over every
archived klc ticket". This report replaces that evidence with a like-for-like
measurement: BEFORE (pre-KLC-108, git e102e70) and AFTER (shipped KLC-108, git
e80d6cd) scored over the IDENTICAL 111-ticket corpus, the same ground truth
(`planning-eval.git_touched`), and the same `rank_metrics` scorer on both
sides — reconstructed in two isolated git worktrees so the live checkout was
never touched (see `[!DECISION D-108-9]`, `.klc/tickets/KLC-108/measure/README.md`).

The honest ratio is 1.23x, not the 1.71x the step-8 evidence recorded — AC-15's
literal "at least 1.5 times" bar does NOT hold on the like-for-like corpus.
This is recorded as `[!QUESTION Q-108-1] blocks=ack` for the operator, not
silently forced to pass and not fixed by retuning a constant (the ratio only
reflects the retriever/rules change; no confidence-threshold constant affects
precision_at_5/recall_at_10 at all). AC-16 (zero high-confidence
zero-precision tickets AFTER) and the recall_at_10 non-regression clause DO
both hold on the same honest corpus.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT = REPO_ROOT / "tests" / "fixtures" / "klc108" / "before_after_report.json"


def _report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_before_and_after_cover_the_same_ticket_corpus():
    """AC-14: a BEFORE run and an AFTER run must cover the same corpus, not
    stored traces built from different index vintages or different ticket
    sets. Asserts the BEFORE and AFTER ticket lists are identical (same 111
    archived tickets), which is the precondition AC-15's ratio comparison
    depends on for its result to be meaningful at all."""
    data = _report()
    before_tickets = set(data["before"]["tickets"])
    after_tickets = set(data["after"]["tickets"])
    assert before_tickets == after_tickets
    assert len(before_tickets) == data["corpus_size"] == 111


def test_after_mean_precision_at_5_ratio_as_measured_like_for_like():
    """AC-15, honesty half: the corpus mean precision_at_5 ratio (AFTER over
    BEFORE) is asserted as MEASURED on the same 111-ticket corpus with the
    same scorer — 1.23x, tolerance +/-0.01 — NOT the spec's literal ">= 1.5
    times" bar, which this like-for-like measurement does not clear (see
    [!QUESTION Q-108-1] blocks=ack in impl-plan.md/build-log.md for the
    operator decision this raises). The stale 3-probe pin (0.1333) is no
    longer the BEFORE baseline; the honest BEFORE mean (0.1964) is."""
    data = _report()
    before_p5 = data["before"]["mean_precision_at_5"]
    after_p5 = data["after"]["mean_precision_at_5"]
    assert before_p5 == 0.19639639639639642
    assert after_p5 == 0.24144144144144145
    ratio = after_p5 / before_p5
    assert abs(ratio - 1.23) <= 0.01, ratio
    assert ratio == data["ratio_precision_at_5_after_over_before"]
    # honest reporting: the bar is recorded as NOT holding, not silently
    # dropped or worked around by retuning a scoring constant.
    assert data["ac15_precision_1_5x_bar_holds"] is False


def test_after_mean_recall_at_10_not_below_before():
    """AC-15's non-regression clause: corpus mean recall_at_10 must not fall
    below its BEFORE value, measured over the same like-for-like 111-ticket
    corpus (honest BEFORE 0.0884, AFTER 0.1038 — this clause DOES hold)."""
    data = _report()
    before_r10 = data["before"]["mean_recall_at_10"]
    after_r10 = data["after"]["mean_recall_at_10"]
    assert after_r10 >= before_r10, (after_r10, before_r10)
    assert data["ac15_recall_non_regression_holds"] is True


def test_after_zero_tickets_high_confidence_with_zero_precision_at_5():
    """AC-16: over the full AFTER corpus (every archived ticket with a
    recoverable diff, the same 111-ticket like-for-like corpus), the count of
    tickets reporting `confidence: high` together with `precision_at_5 == 0`
    is 0 — the eval report names every violating ticket (here, none). The
    BEFORE side is recorded too (45 of 111 violators), to show the honest
    scale of the specific "confidently wrong" failure mode AC-12/AC-16 fix,
    not asserted against by AC-16 itself (AC-16 only judges AFTER)."""
    data = _report()
    after = data["after"]
    assert after["high_confidence_zero_precision_at_5_violators"] == []
    assert after["high_confidence_zero_precision_at_5_count"] == 0
    assert data["corpus_size"] > 0
    # honest BEFORE picture, recorded not asserted-against by AC-16's own bar:
    before = data["before"]
    assert before["high_confidence_zero_precision_at_5_count"] == 45


def test_probe_subset_reconciles_with_spec_pinned_fact_table():
    """AC-16 wording reconciliation (operator-ruled, build-log.md): extracting
    the 3-ticket probe subset (KLC-100/101/102) from THIS like-for-like
    measurement's own full-corpus BEFORE run reproduces the spec's pinned
    FACT-table mean (0.1333) exactly — confirming the probe subset was never
    wrong on its own terms, only unrepresentative of the OLD retriever's
    corpus-wide behaviour (0.1964, 47% higher)."""
    data = _report()
    psr = data["probe_subset_reconciliation"]
    assert psr["spec_pinned_before"]["mean_precision_at_5"] == 0.13333333333333333
    assert psr["this_measurement_before"]["mean_precision_at_5"] == 0.13333333333333333
    for key in ("KLC-100", "KLC-101", "KLC-102"):
        assert key in psr["this_measurement_before"]["tickets"]
        assert psr["this_measurement_before"]["tickets"][key]["confidence"] == "high"
