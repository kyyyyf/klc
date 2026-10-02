"""tests/test_klc154_mapping.py — KLC-154 step-4, AC-7: the finding mapping
follows the spec's Data shapes section in full — an out-of-vocabulary
category keeps the old category in the body as a `[legacy category: X]`
prefix, a `ref` of the form `path:N` with N >= 1 supplies `file`/`line`, and
a first sentence longer than 120 characters is cut at the last word
boundary at or before 120 (the full text stays in `body`). Pinned once by
this parametrized matrix (D-1): eight of the ten cases already pass under
step-1's validity-first mapping; `legacy-category`, `ref-path-n` and
`long-first-sentence` are new behaviour.

Step-7 (external review F-7) adds two more cases and updates
`long-first-sentence`'s expected title: a title is marked with a trailing
'…' (U+2026) whenever it is shorter than the untruncated first sentence —
whether cut by the sentence split or by the 120-character word-boundary cut
— and a literal ellipsis ('...') inside the detail is never read as a
sentence end.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import findings  # noqa: E402
import findings_migrate  # noqa: E402


def _independent(**over):
    rec = {"id": "F-1", "category": "infidelity", "severity": "high",
           "detail": "The spec drifts from the raw intent here.", "ref": "",
           "suggested_fix": None}
    rec.update(over)
    return rec


def _in_client(**over):
    rec = {"severity": "high", "file": "src/foo.py", "line": 10,
           "title": "t", "body": "b", "fix": None}
    rec.update(over)
    return rec


_LONG_DETAIL = "A" * 50 + " " + "B" * 90 + "."

CASES = {
    "independent-in-vocabulary": (
        "spec", _independent(category="infidelity"), 1,
        {"rule_name": "infidelity", "body": "The spec drifts from the raw intent here."}),
    "fix-empty-or-absent-is-null": (
        "spec", _independent(suggested_fix=""), 1,
        {"fix": None}),
    "in-client-id-by-position": (
        "code-review", _in_client(), 7,
        {"id": "F-7"}),
    "in-client-line-zero-is-null": (
        "code-review", _in_client(line=0), 1,
        {"line": None}),
    "in-client-line-null-is-kept": (
        "code-review", _in_client(line=None), 1,
        {"line": None}),
    "drift-artefact-is-spec-md": (
        "drift", _independent(category="decision-violation", ref=""), 1,
        {"file": "spec.md"}),
    "legacy-category": (
        "spec", _independent(category="styling", detail="Formatting nit here."), 1,
        {"rule_name": findings.LEGACY_RULE_NAME,
         "body": "[legacy category: styling] Formatting nit here."}),
    "ref-path-n": (
        "spec", _independent(ref="core/skills/findings.py:42"), 1,
        {"file": "core/skills/findings.py", "line": 42}),
    "ref-non-location": (
        "spec", _independent(ref="see the discussion above"), 1,
        {"file": "spec.md", "line": None, "ref": "see the discussion above"}),
    "long-first-sentence": (
        "spec", _independent(detail=_LONG_DETAIL), 1,
        {"title": "A" * 50 + "…", "body": _LONG_DETAIL}),
    "title-marks-a-short-first-sentence-followed-by-more": (
        "spec", _independent(detail="Two problems. See details below."), 1,
        {"title": "Two problems.…"}),
    "title-does-not-split-on-a-literal-ellipsis": (
        "spec", _independent(detail="See the note ... it explains everything."), 1,
        {"title": "See the note ... it explains everything."}),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_map_finding(case):
    """AC-7: the finding mapping follows the Data-shapes rules exactly."""
    kind, rec, position, expected = CASES[case]
    out = findings_migrate.map_finding(rec, kind, position)
    for key, value in expected.items():
        assert out[key] == value, (case, key, out.get(key), value)


def test_stored_records_are_stamped_finding_dicts():
    """AC-7/Data shapes: stored JSON records are stamped `reviewer`/`kind`
    and round-tripped through `Finding.to_dict()` (`ac: null` becomes
    `ac: ""`), and the migration must not turn it back to null."""
    rec = _in_client()
    out = findings_migrate.map_findings([rec], "code-review", stamp=True)
    assert out[0]["reviewer"] == "code-review"
    assert out[0]["kind"] == "code-review"
    assert out[0]["ac"] == ""
