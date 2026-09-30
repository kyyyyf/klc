"""tests/test_findings.py — KLC-127 step-1: Finding gains optional id, kind, ref, ac
and a nullable line.

Hermetic: no filesystem access outside tmp_path, no git, no subprocess.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import findings  # noqa: E402
from findings import Finding  # noqa: E402


def _base_kwargs(**overrides):
    kwargs = dict(rule_name="rule-x", severity="HIGH", file="f.py", line=None,
                  title="t", body="b", fix=None, reviewer="rev")
    kwargs.update(overrides)
    return kwargs


@pytest.mark.parametrize("mode", ["constructed", "headless-partial-dict"])
def test_finding_from_dict_accepts_optional_fields_with_empty_defaults(mode):
    """AC-1: id, kind, ref, ac default to empty and line=None is accepted."""
    if mode == "constructed":
        f = Finding(**_base_kwargs())
    else:
        # headless-partial-dict: a partial reviewer dict with no id/kind/ref/ac keys
        # at all, and a null line — must not raise TypeError in int(None).
        d = {"rule_name": "rule-x", "severity": "HIGH", "file": "f.py", "line": None,
             "title": "t", "body": "b", "fix": None, "reviewer": "rev"}
        f = Finding.from_dict(d)
    assert f.id == ""
    assert f.kind == ""
    assert f.ref == ""
    assert f.ac == ""
    assert f.line is None


def test_finding_from_dict_round_trips_every_optional_field_when_present():
    """AC-1: from_dict round-trips id, kind, ref and ac when present."""
    d = {"rule_name": "rule-x", "severity": "HIGH", "file": "f.py", "line": 5,
         "title": "t", "body": "b", "fix": "x", "reviewer": "rev",
         "id": "F-1", "kind": "code-review", "ref": "AC-3", "ac": "AC-3"}
    f = Finding.from_dict(d)
    assert f.id == "F-1"
    assert f.kind == "code-review"
    assert f.ref == "AC-3"
    assert f.ac == "AC-3"
    assert f.line == 5


def test_issue_id_byte_identical_to_todays_hash_when_id_kind_ref_all_empty():
    """AC-2: issue_id is byte-identical to today's hash when id/kind/ref are empty (pin)."""
    f = Finding("untestable-ac", "HIGH", "spec.md", 88, "t", "b", None, "spec")
    assert f.issue_id == "fee5eb67461f"


@pytest.mark.parametrize("field_name", ["id", "kind", "ref"])
def test_issue_id_differs_when_id_kind_or_ref_becomes_non_empty(field_name):
    """AC-2: issue_id differs once id, kind or ref becomes non-empty."""
    baseline = Finding("untestable-ac", "HIGH", "spec.md", 88, "t", "b", None, "spec")
    kwargs = _base_kwargs(rule_name="untestable-ac", severity="HIGH", file="spec.md",
                          line=88, title="t", body="b", fix=None, reviewer="spec")
    kwargs[field_name] = "non-empty-value"
    changed = Finding(**kwargs)
    assert changed.issue_id != baseline.issue_id


def test_issue_id_differs_by_title_when_id_is_set():
    """AC-2: when id is non-empty, issue_id also varies by title."""
    kwargs_a = _base_kwargs(rule_name="untestable-ac", severity="HIGH", file="spec.md",
                            line=88, title="title-a", body="b", fix=None,
                            reviewer="spec", id="F-1")
    kwargs_b = dict(kwargs_a, title="title-b")
    a = Finding(**kwargs_a)
    b = Finding(**kwargs_b)
    assert a.issue_id != b.issue_id


def test_aggregate_keeps_todays_behaviour_on_an_unchanged_partials_fixture(tmp_path):
    """AC-1: aggregate still skips a non-list file and an entry missing rule_name (pin)."""
    reviewer_dir = tmp_path / "some-reviewer"
    reviewer_dir.mkdir()
    (reviewer_dir / "findings.json").write_text(
        '[{"rule_name": "r", "severity": "HIGH", "file": "f.py", "line": 1, '
        '"title": "t", "body": "b", "fix": null, "reviewer": "some-reviewer"}, '
        '{"severity": "HIGH", "file": "f.py", "line": 2, "title": "t2", "body": "b2", '
        '"fix": null, "reviewer": "some-reviewer"}]',
        encoding="utf-8",
    )
    other_dir = tmp_path / "other-reviewer"
    other_dir.mkdir()
    (other_dir / "findings.json").write_text('{"not": "a list"}', encoding="utf-8")

    result = findings.aggregate(tmp_path)
    assert len(result) == 1
    assert result[0].rule_name == "r"


def test_sort_for_report_orders_a_null_line_before_line_one():
    """AC-1: sort_for_report orders a null line before line 1 for the same file."""
    with_line = Finding(**_base_kwargs(file="a.py", line=1))
    without_line = Finding(**_base_kwargs(file="a.py", line=None))
    ordered = findings.sort_for_report([with_line, without_line])
    assert ordered == [without_line, with_line]


def test_dispatch_error_finding_with_line_zero_still_constructs():
    """AC-1: the build_orchestrator synthetic dispatch-error finding (line=0) still
    constructs (pin)."""
    f = Finding(rule_name="dispatch-error", severity="CRITICAL", file="(reviewer)",
               line=0, title="Reviewer dispatch failed", body="dispatch rc=1",
               fix=None, reviewer="orchestrator")
    assert f.line == 0
    assert f.issue_id
