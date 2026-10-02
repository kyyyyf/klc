"""tests/test_handback.py — KLC-127 step-2: validate_handback and
validate_findings for the six review kinds (AC-3, AC-4).

Hermetic: no filesystem access outside tmp_path (none needed here), no git,
no subprocess. `handback.py` is pure validation at this step; `take` lands
in step-3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import handback  # noqa: E402


# --- helpers -----------------------------------------------------------------

def _finding(**overrides) -> dict:
    d = {"id": "F-1", "rule_name": "infidelity", "severity": "HIGH", "file": "spec.md",
         "line": 5, "title": "a title", "body": "a body", "fix": None}
    d.update(overrides)
    return d


def _handback(findings=None, decisions=None, **extra) -> dict:
    doc = {"findings": [] if findings is None else findings,
           "decisions_to_confirm": [] if decisions is None else decisions}
    doc.update(extra)
    return doc


def _rule_name_for(kind: str) -> str:
    spec = handback.KINDS[kind]
    return spec.rule_names[0] if spec.rule_names else "readability"


def _clean_finding(kind_name: str, **overrides) -> dict:
    d = _finding(rule_name=_rule_name_for(kind_name), reviewer=kind_name, kind=kind_name)
    d.update(overrides)
    return d


# --- hostile cases -----------------------------------------------------------

def test_unknown_kind_is_reported():
    """AC-4: an unknown kind is a named error, for both entry points."""
    errors = handback.validate_handback("not-a-kind", _handback())
    assert any("unknown kind" in e for e in errors)
    errors = handback.validate_findings("not-a-kind", [])
    assert any("unknown kind" in e for e in errors)


@pytest.mark.parametrize("case", ["top-level-list", "findings-string",
                                  "finding-int", "decisions-string"])
def test_non_dict_verdict_and_non_list_findings_are_reported(case):
    """AC-4: a non-dict verdict, a non-list findings, a non-dict finding, and a
    non-list decisions_to_confirm are each reported."""
    if case == "top-level-list":
        errors = handback.validate_handback("spec", [_clean_finding("spec")])
        assert any("JSON object" in e for e in errors)
    elif case == "findings-string":
        errors = handback.validate_handback("spec", _handback(findings="oops"))
        assert any("findings must be a list" in e for e in errors)
    elif case == "finding-int":
        errors = handback.validate_handback("spec", _handback(findings=[42]))
        assert any("not an object" in e for e in errors)
    else:
        errors = handback.validate_handback("spec", _handback(decisions="oops"))
        assert any("decisions_to_confirm must be a list" in e for e in errors)


@pytest.mark.parametrize("old_key", ["category", "detail", "suggested_fix"])
def test_old_independent_shape_is_reported(old_key):
    """AC-4: a finding carrying an old independent-shape key is refused."""
    finding = _clean_finding("spec", **{old_key: "x"})
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert any("old independent shape" in e and old_key in e for e in errors)


@pytest.mark.parametrize("missing", ["id", "rule_name"])
def test_old_inclient_shape_is_reported(missing):
    """AC-4: a finding missing id or rule_name is the old in-client shape."""
    finding = _clean_finding("spec")
    if missing == "id":
        finding["id"] = ""
    else:
        del finding["rule_name"]
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert any("old in-client shape" in e for e in errors)


@pytest.mark.parametrize("kind,bad_rule", [("spec", "made-up-rule"),
                                          ("code-review", "Not A Slug")])
def test_unknown_rule_name_is_reported(kind, bad_rule):
    """AC-4: an unknown rule_name (fixed vocabulary or non-slug) is reported."""
    finding = _clean_finding(kind, rule_name=bad_rule)
    errors = handback.validate_handback(kind, _handback(findings=[finding]))
    assert any("unknown rule_name" in e for e in errors)


@pytest.mark.parametrize("severity", ["URGENT", "high"])
def test_unknown_severity_is_reported(severity):
    """AC-4: an unknown or wrongly-cased severity is reported."""
    finding = _clean_finding("spec", severity=severity)
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert any("unknown severity" in e for e in errors)


@pytest.mark.parametrize("field_name,value", [("file", ""), ("title", ""), ("body", ""),
                                              ("title", "   "),
                                              ("title", "line one\nline two")])
def test_empty_file_title_or_body_is_reported(field_name, value):
    """AC-4: an empty (or whitespace-only) file/title/body, and a multi-line
    title, are each reported."""
    finding = _clean_finding("spec", **{field_name: value})
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert errors


def test_line_zero_is_reported_as_never_valid():
    """AC-4: line 0 is never valid."""
    finding = _clean_finding("spec", line=0)
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert any("line" in e for e in errors)


def test_line_none_is_valid_for_a_drift_finding_on_spec_md():
    """AC-4: a null line is valid (a drift finding on spec.md)."""
    finding = _clean_finding("drift", file="spec.md", line=None)
    errors = handback.validate_handback("drift", _handback(findings=[finding]))
    assert errors == []


def test_negative_line_is_reported():
    """AC-4: a negative line is reported."""
    finding = _clean_finding("spec", line=-1)
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert any("line" in e for e in errors)


@pytest.mark.parametrize("bad_line", ["42", 4.5, True])
def test_non_integer_non_null_line_is_reported(bad_line):
    """AC-4: a string, float or bool line is reported (not a valid integer)."""
    finding = _clean_finding("spec", line=bad_line)
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert any("line" in e for e in errors)


def test_duplicate_id_within_one_handback_is_reported():
    """AC-4: two findings sharing one id in the same hand-back are reported."""
    f1 = _clean_finding("spec", id="F-1", line=5)
    f2 = _clean_finding("spec", id="F-1", line=9)
    errors = handback.validate_handback("spec", _handback(findings=[f1, f2]))
    assert any("duplicate id" in e for e in errors)


def test_same_location_different_ids_is_not_a_duplicate():
    """AC-4: same file/line/rule_name but different ids is NOT a duplicate."""
    f1 = _clean_finding("spec", id="F-1", line=5)
    f2 = _clean_finding("spec", id="F-2", line=5)
    errors = handback.validate_handback("spec", _handback(findings=[f1, f2]))
    assert errors == []


@pytest.mark.parametrize("scenario", ["reviewer-code-review-on-external",
                                      "reviewer-external-on-code-review",
                                      "kind-names-another-kind"])
def test_reviewer_not_matching_kind_is_reported(scenario):
    """AC-4: a reviewer or kind field naming a different kind is reported."""
    if scenario == "reviewer-code-review-on-external":
        finding = _clean_finding("external-review", reviewer="code-review")
        errors = handback.validate_handback("external-review", _handback(findings=[finding]))
    elif scenario == "reviewer-external-on-code-review":
        finding = _clean_finding("code-review", reviewer="external-review")
        errors = handback.validate_handback("code-review", _handback(findings=[finding]))
    else:
        finding = _clean_finding("code-review", kind="external-review")
        errors = handback.validate_handback("code-review", _handback(findings=[finding]))
    assert errors


def test_reviewer_omitted_validates_clean():
    """AC-3: a hand-back with reviewer omitted entirely still validates clean."""
    finding = _clean_finding("spec")
    del finding["reviewer"]
    errors = handback.validate_handback("spec", _handback(findings=[finding]))
    assert errors == []


@pytest.mark.parametrize("decision", [
    {"id": "D-1", "topic": "scope", "question": "q?", "recommended": ""},
    {"id": "D-1", "topic": "scope", "question": "q?"},
])
def test_decision_without_recommended_is_reported(decision):
    """AC-4: a decision missing (or with empty) recommended is reported."""
    errors = handback.validate_handback("spec", _handback(decisions=[decision]))
    assert any("recommended" in e for e in errors)


@pytest.mark.parametrize("level", ["top-level", "finding-level"])
def test_unknown_extra_keys_are_tolerated(level):
    """AC-4/D-107: an unrecognized extra key, top level or finding level, is
    tolerated, not refused."""
    if level == "finding-level":
        finding = _clean_finding("spec", extra_finding_key="whatever")
        doc = _handback(findings=[finding])
    else:
        finding = _clean_finding("spec")
        doc = _handback(findings=[finding])
        doc["extra_top_key"] = "whatever"
    errors = handback.validate_handback("spec", doc)
    assert errors == []


def test_validate_findings_accepts_a_stored_list_with_stamped_fields_and_issue_id():
    """AC-3: a stored list of Finding dicts (reviewer/kind stamped, issue_id
    present) validates clean through validate_findings."""
    import findings as _findings
    f = _findings.Finding.from_dict(_clean_finding("code-review", reviewer="code-review"))
    items = [f.to_dict()]
    assert items[0]["issue_id"]
    assert handback.validate_findings("code-review", items) == []


@pytest.mark.parametrize("scenario", ["matching-kind-passes", "mismatched-kind-fails"])
def test_validate_findings_accepts_headless_reviewer_names_and_rejects_a_kind_mismatch(scenario):
    """AC-3/D-118: a headless reviewer name (not equal to the kind) is accepted
    by validate_findings; a mismatched `kind` field is still rejected."""
    if scenario == "matching-kind-passes":
        good = _clean_finding("code-review", reviewer="architecture", kind="code-review")
        assert handback.validate_findings("code-review", [good]) == []
    else:
        bad = _clean_finding("code-review", reviewer="architecture", kind="external-review")
        errors = handback.validate_findings("code-review", [bad])
        assert errors


@pytest.mark.parametrize("entry_point", ["handback", "stored"])
def test_legacy_unclassified_is_refused_in_a_handback_and_accepted_in_a_stored_list(entry_point):
    """AC-4/D-118/Q-103: LEGACY_RULE_NAME is refused as a fresh hand-back but
    accepted in an already-stored list (written only by the KLC-154
    migration)."""
    import findings as _findings
    finding = _clean_finding("code-review", rule_name=_findings.LEGACY_RULE_NAME,
                             reviewer="code-review")
    if entry_point == "handback":
        errors = handback.validate_handback("code-review", _handback(findings=[finding]))
        assert any("reserved" in e for e in errors)
    else:
        errors = handback.validate_findings("code-review", [finding])
        assert errors == []


@pytest.mark.parametrize("kind", ["spec", "code-review"])
def test_legacy_unclassified_refused_with_reserved_message(kind):
    """AC-15: a hand-back carrying `rule_name: legacy-unclassified` is
    refused with a message naming the KLC-154 migration as the reason the
    value is reserved — never the kebab-case-slug wording — for both a
    fixed-vocabulary kind (spec) and a free-vocabulary kind (code-review)."""
    import findings as _findings
    finding = _clean_finding(kind, rule_name=_findings.LEGACY_RULE_NAME)
    errors = handback.validate_handback(kind, _handback(findings=[finding]))
    joined = " ".join(errors)
    assert "reserved for the KLC-154 migration" in joined, errors
    assert "kebab-case" not in joined
    assert "slug" not in joined


def test_unknown_free_vocabulary_slug_keeps_the_kebab_case_hint():
    """Regression guard: a genuinely unknown free-vocabulary slug (NOT
    `legacy-unclassified`) keeps today's kebab-case-hint message exactly."""
    finding = _clean_finding("code-review", rule_name="Not Kebab Case")
    errors = handback.validate_handback("code-review", _handback(findings=[finding]))
    assert any(
        "unknown rule_name 'Not Kebab Case' — rule_name must be a "
        "lower-case kebab-case slug (letters, digits and hyphens only, "
        "e.g. 'missing-test'), not snake_case, Title Case or a placeholder" in e
        for e in errors
    ), errors


# --- the clean path ------------------------------------------------------------

@pytest.mark.parametrize("kind", ["spec", "test-plan", "impl-plan", "drift",
                                  "code-review", "external-review"])
def test_validate_handback_and_validate_findings_return_empty_for_a_clean_verdict_of_each_kind(kind):
    """AC-3: a clean verdict of each of the six kinds validates with zero errors,
    built from the kind's own real rule_name/topic vocabulary."""
    finding = _clean_finding(kind)
    doc = _handback(findings=[finding])
    assert handback.validate_handback(kind, doc) == []
    assert handback.validate_findings(kind, [finding]) == []


@pytest.mark.parametrize("kind", ["code-review", "external-review"])
def test_code_review_and_external_review_require_empty_decisions_to_confirm(kind):
    """AC-3: code-review and external-review carry no decision topics, so a
    non-empty decisions_to_confirm is refused."""
    decision = {"id": "D-1", "topic": "scope", "question": "q?", "recommended": "r"}
    errors = handback.validate_handback(kind, _handback(decisions=[decision]))
    assert any("decisions_to_confirm must be empty" in e for e in errors)
