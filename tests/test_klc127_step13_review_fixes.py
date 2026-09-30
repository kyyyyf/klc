#!/usr/bin/env python3
"""tests/test_klc127_step13_review_fixes.py — KLC-127 step-13: external
reviewer round 2 (review/external-review-findings.json, 3 still-open items
after step-12's 5/7).

Item 1 (MEDIUM): `_meaningful_overlap` widened from "share >= 1 non-generic
token" to "share >= 3 tokens outside a wider function-word list (English
review boilerplate + a short Russian list)" — a single incidentally-shared
word (a function name, a stray connective) is not evidence of the same
defect with realistic (not title-doubled-as-body) bodies.

Item 2 (LOW): review.md's Integrity checks bullet described the retired
`[SEVERITY]`-header count and never said `take` REPLACES the stored file.

Item 3 (LOW): `handback.take --ticket` now validates the intake key shape
and requires an existing `meta.json` before touching the filesystem, and a
retry of an already-kept rejected copy does not save a second one.

Hermetic: no git/subprocess; PROJECT_ROOT points at tmp_path throughout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import findings  # noqa: E402
import handback  # noqa: E402
from findings import Finding  # noqa: E402

CORE_AGENTS = FW_ROOT / "core" / "agents"
PLUGIN_AGENTS = FW_ROOT / "klc-plugin" / "agents"
REPLAY = FW_ROOT / "tests" / "fixtures" / "klc127-replay"
TICKETS = ("KLC-133", "KLC-137", "KLC-139")


def _f(**overrides):
    kwargs = dict(rule_name="rule-x", severity="MEDIUM", file="f.py", line=1,
                 title="t", body="b", fix=None, reviewer="code-review",
                 id="", kind="code-review", ref="", ac="")
    kwargs.update(overrides)
    return Finding(kwargs["rule_name"], kwargs["severity"], kwargs["file"],
                  kwargs["line"], kwargs["title"], kwargs["body"], kwargs["fix"],
                  kwargs["reviewer"], kwargs["id"], kwargs["kind"], kwargs["ref"],
                  kwargs["ac"])


# --- item 1: realistic-body generic-vocabulary / Russian-function-word guard

@pytest.mark.parametrize("title_a,body_a,title_b,body_b", [
    ("Missing test for error path", "No test exercises the error path here.",
     "Missing test for timeout handling", "No test exercises the timeout handling here."),
    ("Unused import", "This import is never used anywhere.",
     "Unused variable", "This variable is never used anywhere."),
    ("Missing docstring for parse()", "The parse() function has no docstring.",
     "Missing validation in parse()", "The parse() function has no validation."),
    # F-4's own verbatim verified examples (review/external-review-findings.json)
    ("Missing test for error path", "The error path in parse() has no test.",
     "Missing test for timeout handling", "The timeout in fetch() has no test coverage."),
    ("Unused import", "json is imported but unused.",
     "Unused variable", "tmp is assigned but never used."),
])
def test_realistic_bodies_with_generic_overlap_never_merge(title_a, body_a, title_b, body_b):
    """Item 1 (MEDIUM): with a REALISTIC one-sentence body (not title used
    again as body), these pairs from the external reviewer's F-4 finding —
    including its own verbatim examples, which scored 0.30/0.20 and merged
    before this fix — still clear min_similarity on the old (>= 1
    non-generic token) rule but must not merge: sharing only a function
    name or generic connectives is not evidence of the same defect."""
    a = _f(title=title_a, body=body_a)
    b = _f(reviewer="external-review", kind="external-review", title=title_b, body=body_b)
    groups = findings.group([a, b], 0.15)
    assert len(groups) == 2, f"{title_a!r} / {title_b!r} must not merge"


def test_two_shared_non_generic_tokens_is_still_not_enough():
    """Item 1: the threshold is a COUNT (>= 3), not a boolean — exactly 2
    shared non-generic tokens must not merge either (the old rule needed
    only 1). Distinct titles so the title itself contributes no shared
    tokens; only the two chosen body words do."""
    a = _f(title="Zebra quokka narwhal", body="alpha bravo charlie delta")
    b = _f(reviewer="external-review", kind="external-review",
          title="Yak ocelot platypus", body="alpha bravo echo foxtrot")
    shared = (findings._tokens(a) & findings._tokens(b))
    meaningful = shared - findings._GENERIC_VOCAB
    assert len(meaningful) == 2, f"fixture must share exactly 2, got {meaningful!r}"
    assert not findings._meaningful_overlap(a, b)


def test_three_shared_non_generic_tokens_is_enough():
    """Item 1 positive twin: the same fixture shape with a third shared
    non-generic token now clears the bar."""
    a = _f(title="Zebra quokka narwhal", body="alpha bravo charlie delta")
    b = _f(reviewer="external-review", kind="external-review",
          title="Yak ocelot platypus", body="alpha bravo charlie echo")
    meaningful = (findings._tokens(a) & findings._tokens(b)) - findings._GENERIC_VOCAB
    assert len(meaningful) == 3, f"fixture must share exactly 3, got {meaningful!r}"
    assert findings._meaningful_overlap(a, b)


def test_russian_function_words_alone_never_merge():
    """Item 1: two unrelated Russian findings sharing only function words
    (в, и, не, нет, это) plus one function name score 0.273 on the
    Jaccard alone (real, verified figure) and must not merge — the short
    Russian stop-list drops the function words from both the score and the
    overlap count, leaving only the one shared function name."""
    a = _f(title="Ошибка в функции process_order",
          body="Это не проверяет входные данные и падает при нуле.")
    b = _f(reviewer="external-review", kind="external-review",
          title="Утечка памяти в функции process_order",
          body="Это не освобождает буфер и растёт без остановки.")
    meaningful = (findings._tokens(a) & findings._tokens(b)) - findings._GENERIC_VOCAB
    assert len(meaningful) < findings.MIN_MEANINGFUL_SHARED, meaningful
    groups = findings.group([a, b], 0.15)
    assert len(groups) == 2


def test_replay_corpus_every_true_pair_clears_the_new_threshold_with_margin():
    """Item 1 regression guard: every one of the 12 real true pairs in the
    committed replay corpus still shares well over MIN_MEANINGFUL_SHARED
    non-generic tokens (the reviewer's own measurement: every real
    cross-reviewer duplicate over KLC-110..153 shares >= 4; our corpus's
    minimum is checked here so the margin is never silently eaten by a
    future vocabulary change)."""
    min_seen = None
    for ticket in TICKETS:
        items = []
        for kind in ("code-review", "external-review"):
            path = REPLAY / f"{ticket}-{kind}-findings.json"
            for d in json.loads(path.read_text(encoding="utf-8")):
                items.append(Finding.from_dict(d))
        pairs = json.loads((REPLAY / f"{ticket}-pairs.json").read_text(encoding="utf-8"))
        by_key = {f"{f.reviewer}:{f.id}": f for f in items}
        for p in pairs["true_pairs"]:
            a, b = by_key[p[0]], by_key[p[1]]
            count = len((findings._tokens(a) & findings._tokens(b)) - findings._GENERIC_VOCAB)
            min_seen = count if min_seen is None else min(min_seen, count)
    assert min_seen is not None and min_seen >= 4, (
        f"a real true pair now shares only {min_seen} meaningful tokens, "
        f"below the reviewer's own measured floor of 4"
    )


def test_replay_corpus_pins_still_hold_after_the_widened_threshold():
    """Item 1 regression guard: the step-6/AC-21 replay pins (12 merges, 0
    false merges, pooled 4/6/7) are unmoved by the widened guard."""
    total_merges = 0
    per_ticket_pooled = []
    for ticket in TICKETS:
        items = []
        for kind in ("code-review", "external-review"):
            path = REPLAY / f"{ticket}-{kind}-findings.json"
            for d in json.loads(path.read_text(encoding="utf-8")):
                items.append(Finding.from_dict(d))
        groups = findings.group(items, findings.min_similarity())
        total_merges += sum(len(g) - 1 for g in groups if len(g) > 1)
        per_ticket_pooled.append(len(groups))
    assert total_merges == 12
    assert per_ticket_pooled == [4, 6, 7]


# --- item 2: review.md's Integrity checks bullet matches the JSON pipeline -

@pytest.mark.parametrize("path", [CORE_AGENTS / "review.md", PLUGIN_AGENTS / "review.md"])
def test_integrity_checks_describes_findings_json_and_replace_semantics(path):
    """Item 2 (LOW): the Integrity checks section no longer claims issues
    are counted from `[SEVERITY]` headers only (step 3 already moved to
    `findings.json`), and it now states that `take` REPLACES the stored
    file rather than appending to it."""
    text = path.read_text(encoding="utf-8")
    idx = text.index("## Integrity checks")
    section = text[idx:]
    assert "counted from `[SEVERITY]` headers only" not in section
    assert "findings.json" in section
    assert "REPLACES" in section or "replaces" in section


# --- item 3: take --ticket validates the key and an existing meta.json -----

TICKET = "KLC-993"


def _seed(project: Path, ticket: str = TICKET) -> Path:
    tdir = project / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "review:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return tdir


def _valid_doc():
    return {"findings": [{"id": "F-1", "rule_name": "missing-test", "severity": "HIGH",
                          "file": "f.py", "line": 1, "title": "t", "body": "b", "fix": None}],
           "decisions_to_confirm": []}


@pytest.mark.parametrize("bad_ticket", [
    "../../etc", "klc-993", "KLC/993", "KLC-993/../x", "", "KLC-993; rm -rf /",
    "KLC-993\n", " KLC-993",
])
def test_take_refuses_an_invalid_ticket_key_before_touching_disk(tmp_path, monkeypatch, bad_ticket):
    """Item 3 (LOW): a ticket string that does not match the intake key
    shape is refused before any path is joined or any directory created —
    closes the path-traversal / typo'd-directory hole."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_valid_doc()), encoding="utf-8")

    rc = handback.take("code-review", bad_ticket, vfile)

    assert rc == 1
    # nothing under .klc/tickets was created for this call
    tickets_dir = project / ".klc" / "tickets"
    assert not tickets_dir.exists() or not any(tickets_dir.iterdir())


def test_take_refuses_a_well_shaped_ticket_with_no_meta_json(tmp_path, monkeypatch):
    """Item 3: a ticket string that matches the key shape but has never
    been created (no meta.json) is refused, not silently turned into a
    fresh `.klc/tickets/<typo>/review/` directory."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_valid_doc()), encoding="utf-8")

    rc = handback.take("code-review", "KLC-404404", vfile)

    assert rc == 1
    tdir = project / ".klc" / "tickets" / "KLC-404404"
    assert not tdir.exists()


def test_take_accepts_a_valid_ticket_with_meta_json(tmp_path, monkeypatch):
    """Item 3 positive twin: the new checks do not break the ordinary path."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    _seed(project)
    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps(_valid_doc()), encoding="utf-8")

    rc = handback.take("code-review", TICKET, vfile)

    assert rc == 0


def test_retrying_a_kept_rejected_copy_does_not_multiply_copies(tmp_path, monkeypatch):
    """Item 3: submitting an invalid answer keeps one rejected copy; feeding
    THAT SAME kept copy back in on a retry (still invalid) must not save a
    second, third, ... copy under a fresh timestamp — the operator is
    already working from the one file the retry command names."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    tdir = _seed(project)
    bad = json.dumps({"findings": [{"id": "F-1", "rule_name": "test_coverage",
                                    "severity": "HIGH", "file": "f.py", "line": 1,
                                    "title": "t", "body": "b", "fix": None}],
                      "decisions_to_confirm": []})
    vfile = tmp_path / "verdict.json"
    vfile.write_text(bad, encoding="utf-8")

    rc1 = handback.take("code-review", TICKET, vfile)
    assert rc1 == 1
    rejected = list((tdir / "review").glob("code-review-rejected-*.txt"))
    assert len(rejected) == 1
    kept_path = rejected[0]

    # retry, feeding the KEPT COPY itself back in (still invalid) -----------
    rc2 = handback.take("code-review", TICKET, kept_path)
    assert rc2 == 1
    rejected_after = list((tdir / "review").glob("code-review-rejected-*.txt"))
    assert len(rejected_after) == 1, (
        "retrying a kept rejected copy must not save a second copy"
    )
    assert rejected_after[0] == kept_path


def test_a_fresh_invalid_file_outside_review_dir_still_gets_kept_normally(tmp_path, monkeypatch):
    """Item 3 negative twin: the skip-save rule is scoped to files already
    inside THIS ticket's own review/ directory named like a rejected copy —
    an ordinary fresh submission is still kept exactly as step-12 intends."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    tdir = _seed(project)
    bad = json.dumps({"findings": [{"id": "F-1", "rule_name": "test_coverage",
                                    "severity": "HIGH", "file": "f.py", "line": 1,
                                    "title": "t", "body": "b", "fix": None}],
                      "decisions_to_confirm": []})
    vfile = tmp_path / "verdict.json"
    vfile.write_text(bad, encoding="utf-8")

    rc = handback.take("code-review", TICKET, vfile)

    assert rc == 1
    assert len(list((tdir / "review").glob("code-review-rejected-*.txt"))) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
