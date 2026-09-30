#!/usr/bin/env python3
"""tests/test_klc127_step12_review_fixes.py — KLC-127 step-12: review round 1
fixes.

F-1 (HIGH): review.md's section 4 names `--kind external-review` for the
external answer, never `--kind code-review` (which silently overwrote the
code reviewer's own stored file and hid the external pass from the pool).

F-2 (HIGH): the free-vocabulary kinds (code-review/external-review) are told
`rule_name` must be a lower-case kebab-case slug, the template's focus list
and instructions are kebab-case and name the empty-decisions rule, and a
refused answer is kept on disk (never lost) with a printed retry command.

F-3 (MEDIUM): `duplicate_rate` is null unless at least two distinct
reviewers contributed a review-kind finding, and `reviewers` names them.

F-4 (MEDIUM): dedupe tokenizes Unicode words, normalises file paths (a bare
basename matches its one unambiguous file), and never merges two findings
whose only shared vocabulary is generic review boilerplate.

F-5 (LOW): `extract_verdict` finds a real verdict even when a later,
unrelated JSON block (e.g. the completion-signal) follows it; a hand-back
with decisions but no `findings` key is treated the same by intake as by
the ack-time parser.

F-7 (LOW): the old-shape skip note names the KLC-154 migration.

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


def _seed_meta(project: Path, ticket: str) -> None:
    """step-13/item-3: `handback.take` now refuses a ticket with no
    `meta.json` (never creates one), so every test that calls `take`
    against a fresh tmp_path ticket must seed one first."""
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
PLUGIN_AGENTS = FW_ROOT / "klc-plugin" / "agents"


# --- F-1: the external answer is taken in with --kind external-review -------

@pytest.mark.parametrize("path", [CORE_AGENTS / "review.md", PLUGIN_AGENTS / "review.md"])
def test_review_md_section_4_names_external_review_kind_for_the_external_answer(path):
    """F-1 (HIGH): review.md's section 4 (and its plugin twin) name
    `--kind external-review` for the external answer — never take it in
    under `--kind code-review`, which silently overwrites the code
    reviewer's own stored file (an atomic whole-file write) and hides the
    external pass from the pool."""
    text = path.read_text(encoding="utf-8")
    idx = text.index("### 4. External reviewer")
    end = text.index("### 5.", idx)
    section = text[idx:end]
    assert "--kind external-review" in section, (
        f"{path}: section 4 never names --kind external-review for the external answer"
    )


@pytest.mark.parametrize("path", [CORE_AGENTS / "external-review.md",
                                  PLUGIN_AGENTS / "external-review.md"])
def test_external_review_md_names_its_own_kind(path):
    """F-1 regression guard: external-review.md's own step 4 (the thing
    review.md's section 4 must agree with) still names its real kind."""
    text = path.read_text(encoding="utf-8")
    assert "handback.py take --kind external-review" in text


# --- F-2: rule_name kebab-case guidance + retry-safe refusal ----------------

@pytest.mark.parametrize("bad_rule", ["test_coverage", "RULE"])
def test_free_vocab_rule_name_refusal_names_the_kebab_case_fix(bad_rule):
    """F-2 (HIGH): a free-vocabulary kind (external-review) refuses a
    non-kebab-case rule_name with a message that NAMES the fix (kebab-case),
    not just 'unknown' — so a one-shot provider's reply can be corrected."""
    doc = {"findings": [{"id": "F-1", "rule_name": bad_rule, "severity": "HIGH",
                         "file": "f.py", "line": 1, "title": "t", "body": "b",
                         "fix": None}],
          "decisions_to_confirm": []}
    errors = handback.validate_handback("external-review", doc)
    assert errors
    assert any("kebab-case" in e for e in errors), errors


def test_refused_answer_is_kept_on_disk_with_a_retry_command(tmp_path, monkeypatch, capsys):
    """F-2 (HIGH): when intake refuses an external-review answer (a schema
    error), the raw text is kept at review/<kind>-rejected-<ts>.txt and the
    exact retry command is printed to stderr — the answer is never simply
    lost, which matters for a one-shot HTTP provider that will not be
    re-queried automatically."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    _seed_meta(project, "KLC-991")
    raw = json.dumps({"findings": [{"id": "F-1", "rule_name": "test_coverage",
                                    "severity": "HIGH", "file": "f.py", "line": 1,
                                    "title": "t", "body": "b", "fix": None}],
                      "decisions_to_confirm": []})
    vfile = tmp_path / "verdict.json"
    vfile.write_text(raw, encoding="utf-8")

    rc = handback.take("external-review", "KLC-991", vfile)

    assert rc == 1
    tdir = project / ".klc" / "tickets" / "KLC-991"
    rejected = list((tdir / "review").glob("external-review-rejected-*.txt"))
    assert len(rejected) == 1, "the raw answer must be kept on disk, never lost"
    assert rejected[0].read_text(encoding="utf-8") == raw
    err = capsys.readouterr().err
    assert "retry with" in err
    assert str(rejected[0]) in err


def test_a_valid_answer_is_not_kept_as_rejected(tmp_path, monkeypatch):
    """F-2 negative twin: a VALID verdict is stored normally and leaves no
    rejected file behind."""
    project = tmp_path / "proj"
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    _seed_meta(project, "KLC-992")
    raw = json.dumps({"findings": [{"id": "F-1", "rule_name": "missing-test",
                                    "severity": "HIGH", "file": "f.py", "line": 1,
                                    "title": "t", "body": "b", "fix": None}],
                      "decisions_to_confirm": []})
    vfile = tmp_path / "verdict.json"
    vfile.write_text(raw, encoding="utf-8")

    rc = handback.take("external-review", "KLC-992", vfile)

    assert rc == 0
    tdir = project / ".klc" / "tickets" / "KLC-992"
    assert not list((tdir / "review").glob("external-review-rejected-*.txt"))


def test_template_renders_kebab_case_focus_and_states_no_decisions():
    """F-2: the rendered external-review prompt uses kebab-case in its focus
    list (config/reviewers.yml's `test-coverage`, not `test_coverage`) and
    explicitly states `decisions_to_confirm` must be empty."""
    from jinja2 import Environment, StrictUndefined
    tpl_path = FW_ROOT / "core" / "templates" / "external-review-prompt.j2"
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    tpl = env.from_string(tpl_path.read_text(encoding="utf-8"))
    schema = (CORE_AGENTS / "_includes" / "finding-schema.md").read_text(encoding="utf-8")
    rendered = tpl.render(spec="s", diff="d", claude_md_context="c",
                          focus_areas=["security", "test-coverage"],
                          finding_schema=schema)
    assert "test_coverage" not in rendered
    assert "test-coverage" in rendered
    assert "decisions_to_confirm" in rendered
    assert "kebab-case" in rendered


def test_config_reviewers_focus_list_is_kebab_case():
    """F-2: config/reviewers.yml's external_reviewer.focus list carries no
    snake_case entries — every other reviewer slug in this repo is kebab-case
    (e.g. the test-coverage reviewer itself), and the external template's
    focus list must match."""
    text = (FW_ROOT / "config" / "reviewers.yml").read_text(encoding="utf-8")
    assert "test_coverage" not in text
    assert "test-coverage" in text


def test_finding_schema_states_the_rule_name_format_briefly():
    """F-2: the shared schema include states the kebab-case rule_name format
    for the free-vocabulary kinds, briefly."""
    text = (CORE_AGENTS / "_includes" / "finding-schema.md").read_text(encoding="utf-8")
    assert "kebab-case" in text


# --- F-3: duplicate_rate null unless >= 2 reviewers contributed -------------

def _f(**overrides):
    kwargs = dict(rule_name="rule-x", severity="MEDIUM", file="f.py", line=1,
                 title="t", body="b", fix=None, reviewer="code-review",
                 id="", kind="code-review", ref="", ac="")
    kwargs.update(overrides)
    return Finding(kwargs["rule_name"], kwargs["severity"], kwargs["file"],
                  kwargs["line"], kwargs["title"], kwargs["body"], kwargs["fix"],
                  kwargs["reviewer"], kwargs["id"], kwargs["kind"], kwargs["ref"],
                  kwargs["ac"])


def test_duplicate_rate_is_null_when_only_one_reviewer_contributed():
    """F-3 (MEDIUM): five findings from ONE reviewer must never read
    duplicate_rate 0.0 — there was no second opinion to (dis)agree with, so
    a structural zero must not enter a track's mean as a real measurement."""
    items = [_f(id=f"F-{i}", title=f"finding {i}", body=f"distinct body {i}")
            for i in range(5)]
    pool = findings.build_pool(items, ticket="KLC-991", min_similarity=0.15)
    assert pool["raw_count"] == 5
    assert pool["duplicate_rate"] is None
    assert pool["reviewers"] == ["code-review"]


def test_duplicate_rate_is_numeric_when_two_reviewers_contributed():
    """F-3: with a second reviewer's finding merged in, the rate is real and
    `reviewers` names both, sorted."""
    a = _f(id="F-1", file="runner.py", title="A title",
          body="modelusage cumulative tokens accounting basis session drift")
    b = _f(id="F-1", reviewer="external-review", kind="external-review",
          file="runner.py", title="B title",
          body="modelusage cumulative tokens accounting basis session drift")
    pool = findings.build_pool([a, b], ticket="KLC-991", min_similarity=0.15)
    assert pool["reviewers"] == ["code-review", "external-review"]
    assert pool["duplicate_rate"] == pytest.approx(0.5)


# --- F-4: Unicode tokens, path normalisation, generic-vocabulary guard ------

def test_cyrillic_findings_score_above_zero():
    """F-4: a Unicode-aware token pattern lets non-ASCII text (Russian prose
    rules, per this repo's own CLAUDE.md) score — the old [a-z0-9_]+ pattern
    dropped every Cyrillic character and always scored 0.0."""
    a = _f(title="Ошибка в обработке токенов", body="функция теряет токены при retry")
    b = _f(reviewer="external-review", kind="external-review",
          title="Ошибка в обработке токенов", body="функция теряет токены при повторе")
    assert findings.similarity(a, b) > 0.0


def test_a_bare_basename_merges_with_its_one_unambiguous_full_path():
    """F-4: 'x.py' and 'core/skills/x.py' are treated as the same file when
    the basename is unique across the item set — different spellings of one
    path must not silently block a real duplicate."""
    a = _f(file="x.py", title="Off-by-one in the range boundary check",
          body="the loop boundary is wrong for the last element case entirely")
    b = _f(reviewer="external-review", kind="external-review",
          file="core/skills/x.py", title="Off-by-one in the range boundary check",
          body="the loop boundary is wrong for the last element case entirely")
    groups = findings.group([a, b], 0.15)
    assert len(groups) == 1


def test_an_ambiguous_basename_does_not_merge_across_two_distinct_files():
    """F-4 negative twin: when TWO distinct full paths share one basename in
    the same item set, a bare basename reference must not pick one of them
    arbitrarily — same-file stays undecided, so no merge."""
    a = _f(file="x.py", title="Off-by-one in the range boundary check",
          body="the loop boundary is wrong for the last element case entirely")
    b = _f(reviewer="external-review", kind="external-review",
          file="core/skills/x.py", title="Off-by-one in the range boundary check",
          body="the loop boundary is wrong for the last element case entirely")
    c = _f(reviewer="drift", kind="drift", file="tests/fixtures/x.py",
          title="an unrelated finding about x.py elsewhere", body="filler")
    groups = findings.group([a, b, c], 0.15)
    # a (bare "x.py") can no longer be assumed to mean b's "core/skills/x.py"
    # once a second "x.py" (c's) exists in the set.
    assert not any(len(g) > 1 and a in g and b in g for g in groups)


@pytest.mark.parametrize("title_a,title_b", [
    ("Missing test for error path", "Missing test for timeout handling"),
    ("Unused import", "Unused variable"),
])
def test_generic_vocabulary_alone_never_merges_two_findings(title_a, title_b):
    """F-4: two findings whose ONLY shared vocabulary is generic review
    boilerplate (missing/test/unused/error/handling) must not merge even
    when the raw Jaccard score clears min_similarity — these are genuinely
    distinct defects, not a real duplicate pair."""
    a = _f(title=title_a, body=title_a)
    b = _f(reviewer="external-review", kind="external-review",
          title=title_b, body=title_b)
    assert findings.similarity(a, b) >= 0.15, (
        "fixture must actually clear the threshold for this guard to mean anything"
    )
    groups = findings.group([a, b], 0.15)
    assert len(groups) == 2, "generic-only overlap must not merge"


def test_the_twelve_zero_replay_pins_stay_green():
    """F-4 regression guard: the step-6 replay fixtures (now flattened,
    step-12/item-9) still give 12 merges / 0 false merges through the real
    `findings.group` with the new tokenizer/path/vocabulary rules."""
    REPLAY = FW_ROOT / "tests" / "fixtures" / "klc127-replay"
    total_merges = total_groups = 0
    for ticket in ("KLC-133", "KLC-137", "KLC-139"):
        items = []
        for kind in ("code-review", "external-review"):
            path = REPLAY / f"{ticket}-{kind}-findings.json"
            for d in json.loads(path.read_text(encoding="utf-8")):
                items.append(Finding.from_dict(d))
        groups = findings.group(items, findings.min_similarity())
        total_merges += sum(len(g) - 1 for g in groups if len(g) > 1)
        total_groups += len(groups)
    assert total_merges == 12
    assert total_groups == 17


def test_klc127_replay_fixture_is_flat_not_nested():
    """Item 9 (regression check): the replay fixture directory holds its
    nine data files (three tickets times pairs/code-review/external-review)
    flat, not in per-ticket/per-kind subdirectories — a fixture directory
    that directly holds files becomes its own module under
    `modules_build.py`'s directory-level clustering (KLC-074); nested
    subdirectories added six extra index modules for nothing and pushed the
    live module count to 86, over `test_modules_cutover_gate.py`'s [25,85]
    band (confirmed failing on this branch before the flatten, passing on
    `main` in the same environment)."""
    replay = FW_ROOT / "tests" / "fixtures" / "klc127-replay"
    assert not any(p.is_dir() for p in replay.iterdir())


# --- F-6: review.md step 3 describes the JSON pipeline; security.md is kebab-case

@pytest.mark.parametrize("path", [CORE_AGENTS / "review.md", PLUGIN_AGENTS / "review.md"])
def test_review_md_step_3_describes_the_json_partial_pipeline(path):
    """F-6 (LOW): step 3 no longer describes the retired `[SEVERITY]`-tag
    extraction as the primary parse rule — it names `findings.json` and the
    schema-error skip-the-whole-file rule (AC-14/AC-22)."""
    text = path.read_text(encoding="utf-8")
    idx = text.index("### 3. Parse partials")
    end = text.index("### 4.", idx)
    section = text[idx:end]
    assert "Extract every issue tagged" not in section
    assert "findings.json" in section
    assert "blocking_severity" in section


def test_security_reviewer_rule_name_is_kebab_case_not_snake_case():
    """F-6 (LOW): core/agents/review/security.md's own catalog is
    kebab-case (e.g. `injection-sql`), so its prose must say kebab-case,
    not snake_case — a model trusting the prose over the list must not get
    its whole partial refused by findings.check_findings's slug regex."""
    text = (CORE_AGENTS / "review" / "security.md").read_text(encoding="utf-8")
    assert "snake_case" not in text
    assert "kebab-case" in text


# --- F-5: extract_verdict verdict-then-signal; missing findings key --------

def test_extract_verdict_finds_the_real_verdict_before_a_trailing_signal_block():
    """F-5 (LOW): a verdict block followed by an unrelated completion-signal
    JSON block (the shape every reviewer prompt's completion-signal include
    asks for as the LAST output) must still resolve to the verdict, not
    None — the docstring's own claim."""
    text = (
        '```json\n{"findings": [], "decisions_to_confirm": []}\n```\n'
        "\nDONE\n"
        '```json\n{"phase": "review", "signal": "done"}\n```\n'
    )
    doc = handback.extract_verdict(text)
    assert doc is not None
    assert doc == {"findings": [], "decisions_to_confirm": []}


def test_extract_verdict_returns_none_when_no_block_carries_the_keys():
    """F-5 negative twin: a lone completion-signal block (no verdict at all)
    is still not a parseable verdict."""
    text = '```json\n{"phase": "review", "signal": "done"}\n```\n'
    assert handback.extract_verdict(text) is None


def test_missing_findings_key_is_treated_as_empty_not_an_error():
    """F-5: a hand-back with decisions but no `findings` key at all is
    accepted (treated as `findings: []`), matching parse_review's own rule
    (`doc.get("findings") or []`) — intake and the ack-time parser now agree
    on the same file shape."""
    doc = {"decisions_to_confirm": []}
    errors = handback.validate_handback("code-review", doc)
    assert errors == []


# --- F-7: the old-shape note names the KLC-154 migration --------------------

def test_old_shape_note_names_the_klc154_migration(tmp_path):
    """F-7 (LOW): an old-shape stored findings file's skip note tells the
    operator the fix is the KLC-154 migration, not just the symptom."""
    tdir = tmp_path / "KLC-1"
    path = tdir / "review" / "code-review-findings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"id": "F-1", "category": "old", "detail": "d",
                                 "suggested_fix": "f", "severity": "high"}]),
                    encoding="utf-8")
    items, notes = handback.load_ticket_findings(tdir)
    assert items == []
    assert len(notes) == 1
    assert "KLC-154" in notes[0]


def test_a_genuinely_invalid_file_gets_no_klc154_mention(tmp_path):
    """F-7 negative twin: a file that fails for a reason OTHER than the
    old shape (e.g. an unknown severity) does not falsely point at the
    KLC-154 migration — that note is reserved for the actual old-shape
    symptom."""
    tdir = tmp_path / "KLC-1"
    path = tdir / "review" / "code-review-findings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"id": "F-1", "rule_name": "missing-test",
                                 "severity": "URGENT", "file": "f.py", "line": 1,
                                 "title": "t", "body": "b", "fix": None}]),
                    encoding="utf-8")
    items, notes = handback.load_ticket_findings(tdir)
    assert items == []
    assert len(notes) == 1
    assert "KLC-154" not in notes[0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
