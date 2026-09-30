"""tests/test_findings_dedupe.py — KLC-127 step-7: the similarity rule and
the new dedupe (AC-19, AC-20).

`findings.dedupe` merges findings from different reviewers on the same file
whose token-Jaccard over title plus the first 200 characters of body reaches
`review.dedupe.min_similarity` (shipped as 0.15, `config/reviewers.yml`),
keeps the highest severity and every contributor, and never merges within
one reviewer, across files, below the threshold, or by `issue_id` alone.

Hostile/negative cases come first (impl-plan.md step-7's own RED order);
the KLC-127 replay fixtures of step-6 (`tests/fixtures/klc127-replay/`) back
the real-corpus assertions. Hermetic: no filesystem access outside the
committed fixtures and tmp_path, no git, no subprocess.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import findings  # noqa: E402
import review_plan  # noqa: E402
from findings import Finding  # noqa: E402

REPLAY = _FW_ROOT / "tests" / "fixtures" / "klc127-replay"


def _f(*, rule_name="rule-x", severity="MEDIUM", file="f.py", line=1, title="t",
       body="b", fix=None, reviewer="rev", id="", kind="", ref="", ac=""):
    return Finding(rule_name, severity, file, line, title, body, fix, reviewer,
                   id, kind, ref, ac)


def _load_replay(ticket: str) -> list[Finding]:
    items = []
    for kind in ("code-review", "external-review"):
        path = REPLAY / f"{ticket}-{kind}-findings.json"
        for d in json.loads(path.read_text(encoding="utf-8")):
            items.append(Finding.from_dict(d))
    return items


# ----------------------------- hostile / negative cases first ---------------

def test_dedupe_keeps_the_eight_klc139_distinct_defect_pairs_within_three_lines_separate():
    """AC-20: the eight distinct-defect pairs in the KLC-139 skeleton.py
    lines 385-388 fixture (code0/code1/code4/ext0/ext4 by 0-based file
    position, test-plan.md's own naming) never land in the same group."""
    items = _load_replay("KLC-139")
    code = [f for f in items if f.reviewer == "code-review"]
    ext = [f for f in items if f.reviewer == "external-review"]
    code0, code1, code4 = code[0], code[1], code[4]
    ext0, ext4 = ext[0], ext[4]
    groups = findings.group(items, findings.min_similarity())

    def same_group(a, b):
        return any(a in g and b in g for g in groups)

    for a, b in ((code0, code1), (code0, code4), (code0, ext0), (code0, ext4),
                 (code1, code4), (code1, ext4), (code4, ext0), (ext0, ext4)):
        assert not same_group(a, b), "false merge among the KLC-139 near-line defects"


@pytest.mark.parametrize("case", ["same-reviewer", "different-file"])
def test_dedupe_never_merges_across_the_same_reviewer_or_different_files(case):
    """AC-20: a reviewer never de-duplicates against itself, and file
    agreement is a hard AND, never a tie-breaker (pin: different-file already
    holds on main's line-window key too)."""
    shared_text = "modelusage tokens cumulative accounting basis mismatch drift"
    if case == "same-reviewer":
        a = _f(file="runner.py", line=88, title="A", body=shared_text, reviewer="code-review")
        b = _f(file="runner.py", line=90, title="A", body=shared_text, reviewer="code-review")
    else:
        a = _f(file="runner.py", line=88, title="A", body=shared_text, reviewer="code-review")
        b = _f(file="other.py", line=88, title="A", body=shared_text, reviewer="external-review")
    result = findings.dedupe([a, b])
    assert len(result) == 2


@pytest.mark.parametrize("case", ["two-reviewers-below-threshold", "one-reviewer-twice"])
def test_dedupe_never_drops_a_finding_because_of_an_equal_issue_id(case):
    """AC-20: two findings that happen to share (rule_name, file, line) and
    empty id/kind/ref — and so the SAME issue_id — are never silently
    collapsed by an issue_id-keyed `seen` set (main's old dedupe bug class)."""
    if case == "two-reviewers-below-threshold":
        a = _f(rule_name="r1", file="f.py", line=10, title="zzunrelated1 findingone",
               body="wordA1 wordA2 wordA3 wordA4 wordA5 wordA6 wordA7 wordA8",
               reviewer="code-review")
        b = _f(rule_name="r1", file="f.py", line=10, title="zzunrelated2 findingtwo",
               body="wordB1 wordB2 wordB3 wordB4 wordB5 wordB6 wordB7 wordB8",
               reviewer="external-review")
    else:
        a = _f(rule_name="r1", file="f.py", line=10, title="alpha", body="same body",
               reviewer="code-review")
        b = _f(rule_name="r1", file="f.py", line=10, title="alpha", body="same body",
               reviewer="code-review")
    assert a.issue_id == b.issue_id
    result = findings.dedupe([a, b])
    assert len(result) == 2


def test_one_group_never_holds_two_findings_of_one_reviewer():
    """AC-20: a chain A1-B-A2 (A1 and A2 from one reviewer, B from another,
    both similar to B) never ends with A1 and A2 in the same group via B."""
    shared_ab1 = "recursion error ast parse deeply nested expression crash"
    shared_ab2 = "bom prefix python file falsely refused syntax errors"
    a1 = _f(rule_name="r1", file="skeleton.py", line=388, title="A1",
            body=shared_ab1, reviewer="code-review")
    a2 = _f(rule_name="r2", file="skeleton.py", line=385, title="A2",
            body=shared_ab2, reviewer="code-review")
    # B shares vocabulary with BOTH a1 and a2 (a bridging finding)
    b = _f(rule_name="r3", file="skeleton.py", line=386, title="B",
          body=shared_ab1 + " " + shared_ab2, reviewer="external-review")
    groups = findings.group([a1, b, a2], 0.15)
    for g in groups:
        reviewers_in_g = [f.reviewer for f in g]
        assert len(reviewers_in_g) == len(set(reviewers_in_g)), \
            "a group holds two findings of one reviewer"


def test_merged_issue_id_is_recomputed_not_inherited():
    """AC-20 (pin): a merged finding's issue_id is freshly computed, not
    inherited from either contributor."""
    shared = "modelusage cumulative tokens accounting basis mismatch drift here"
    a = _f(rule_name="ra", file="runner.py", line=88, title="A", body=shared,
          reviewer="code-review")
    b = _f(rule_name="rb", file="runner.py", line=184, title="B", body=shared,
          reviewer="external-review")
    result = findings.dedupe([a, b])
    assert len(result) == 1
    merged = result[0]
    assert merged.issue_id not in (a.issue_id, b.issue_id)


@pytest.mark.parametrize("union_size,expect_merge", [(20, True), (21, False)])
def test_dedupe_merges_at_the_exact_configured_similarity_boundary(union_size, expect_merge):
    """AC-19: an inclusive >= boundary — 3 of 20 shared tokens merges (score
    exactly 0.15), 3 of 21 does not (score just under 0.15)."""
    shared = ["zzshare1", "zzshare2", "zzshare3"]
    if union_size == 20:
        a_unique = [f"au{i}" for i in range(9)]
        b_unique = [f"bu{i}" for i in range(8)]
    else:
        a_unique = [f"cu{i}" for i in range(9)]
        b_unique = [f"du{i}" for i in range(9)]
    a = _f(file="f.py", line=1, title="", body=" ".join(a_unique + shared),
          reviewer="code-review")
    b = _f(file="f.py", line=2, title="", body=" ".join(b_unique + shared),
          reviewer="external-review")
    score = findings.similarity(a, b)
    if expect_merge:
        assert score == pytest.approx(0.15)
    else:
        assert score < 0.15
    result = findings.dedupe([a, b])
    assert len(result) == (1 if expect_merge else 2)


# ----------------------------- positive-merge cases --------------------------

def test_dedupe_merges_two_findings_naming_the_same_file_above_the_similarity_threshold():
    """AC-19: the real KLC-133 modelUsage pair (code-review F-1 / external-
    review F-1) merges: different rule_name, different line (delta 96), same
    file — highest severity kept, both reviewers and both bodies present."""
    items = _load_replay("KLC-133")
    code_f1 = next(f for f in items if f.reviewer == "code-review" and f.id == "F-1")
    ext_f1 = next(f for f in items if f.reviewer == "external-review" and f.id == "F-1")
    result = findings.dedupe([code_f1, ext_f1])
    assert len(result) == 1
    merged = result[0]
    assert merged.severity == "MEDIUM"
    assert "code-review" in merged.reviewer and "external-review" in merged.reviewer
    assert code_f1.title in merged.body or code_f1.body in merged.body
    assert ext_f1.title in merged.body or ext_f1.body in merged.body


def test_dedupe_keeps_the_higher_severity_not_the_first_when_the_lower_severity_finding_is_listed_first():
    """AC-19: F-004 regression — the real KLC-139 RecursionError HIGH/MEDIUM
    disagreement pair, MEDIUM listed FIRST, HIGH second: merged severity is
    still HIGH (keeps highest, not first-in-list)."""
    items = _load_replay("KLC-139")
    code_f1 = next(f for f in items if f.reviewer == "code-review" and f.id == "F-1")  # HIGH
    ext_f2 = next(f for f in items if f.reviewer == "external-review" and f.id == "F-2")  # MEDIUM
    assert code_f1.severity == "HIGH"
    assert ext_f2.severity == "MEDIUM"
    result = findings.dedupe([ext_f2, code_f1])  # MEDIUM first, HIGH second
    assert len(result) == 1
    assert result[0].severity == "HIGH"


def test_dedupe_ignores_rule_name_and_line_distance_when_similarity_and_file_agree():
    """AC-19: wildly different rule_name and a 96-line delta play no role —
    file agreement plus similarity is the whole predicate."""
    shared = "modelusage cumulative token counts accounting basis session"
    a = _f(rule_name="totally-different-rule-alpha", file="runner.py", line=88,
          title="mixes accounting bases", body=shared, reviewer="code-review")
    b = _f(rule_name="completely-unrelated-rule-beta", file="runner.py", line=184,
          title="mixes accounting bases too", body=shared, reviewer="external-review")
    result = findings.dedupe([a, b])
    assert len(result) == 1


@pytest.mark.parametrize("ticket", ["KLC-133", "KLC-137", "KLC-139", "synthetic-no-merge"])
def test_pooled_plus_merged_counts_always_equal_the_raw_count(ticket):
    """AC-20: pooled plus merged counts always add up to the raw count."""
    if ticket == "synthetic-no-merge":
        items = [_f(file=f"f{i}.py", line=i, title=f"unique {i}",
                    body=f"nothing shared here {i} at all whatsoever",
                    reviewer="code-review")
                 for i in range(5)]
    else:
        items = _load_replay(ticket)
    raw_count = len(items)
    groups = findings.group(items, findings.min_similarity())
    pooled_count = len(groups)
    merged = sum(len(g) - 1 for g in groups if len(g) > 1)
    assert pooled_count + merged == raw_count


def test_similarity_is_case_insensitive_and_drops_stop_words():
    """AC-19: similarity is computed on lower-cased tokens with stop words
    dropped — case and stop-word choice must not move the score."""
    a = _f(title="The Widget Is Broken", body="It is not working with the config",
          file="f.py")
    b = _f(title="the widget is broken", body="it is not working with the config",
          file="f.py")
    assert findings.similarity(a, b) == pytest.approx(1.0)


@pytest.mark.parametrize("case", ["shipped", "missing-file", "tmp-0.30"])
def test_min_similarity_reads_config_and_falls_back_to_0_15(case, monkeypatch):
    """AC-19: `findings.min_similarity` reads `review.dedupe.min_similarity`
    from `config/reviewers.yml` (via `review_plan.load_reviewers_cfg`),
    handles the YAML reader returning a string, falls back to 0.15 when the
    file is missing, and a raised threshold actually flips a merge."""
    if case == "shipped":
        assert findings.min_similarity() == pytest.approx(0.15)
        return
    if case == "missing-file":
        monkeypatch.setattr(review_plan, "load_reviewers_cfg",
                            lambda: ({}, "config/reviewers.yml not found"))
        assert findings.min_similarity() == pytest.approx(0.15)
        return
    # tmp-0.30: the repo's YAML reader returns scalars as strings
    monkeypatch.setattr(
        review_plan, "load_reviewers_cfg",
        lambda: ({"review": {"dedupe": {"min_similarity": "0.30"}}}, None))
    assert findings.min_similarity() == pytest.approx(0.30)
    # the exact-0.15-boundary pair from above merges at 0.15 but not at 0.30
    shared = ["zzshare1", "zzshare2", "zzshare3"]
    a_unique = [f"au{i}" for i in range(9)]
    b_unique = [f"bu{i}" for i in range(8)]
    a = _f(file="f.py", line=1, title="", body=" ".join(a_unique + shared),
          reviewer="code-review")
    b = _f(file="f.py", line=2, title="", body=" ".join(b_unique + shared),
          reviewer="external-review")
    assert len(findings.dedupe([a, b])) == 2  # flipped: no longer merges


def test_dedupe_is_independent_of_input_order():
    """AC-20: the same input set, reordered, produces the same pooling."""
    items = _load_replay("KLC-133")
    forward = findings.dedupe(list(items))
    backward = findings.dedupe(list(reversed(items)))
    key = lambda fs: sorted(f.issue_id for f in fs)  # noqa: E731
    assert key(forward) == key(backward)
    assert len(forward) == len(backward) == 4
