"""KLC-123 step-3 — the dogfood regression (AC-8).

Proves, against THIS repository's own real `.klc/index/*.json` artifacts
(unmodified), that a query whose top-module separation and edit-slice hit
already clear the KLC-108 `high` bar is no longer forced to `low` by the
unrelated, minority `c`-language degradation (`.h` fixtures classified as
`c`, universe 2 / 0 files with symbols) that raw.md's live symptom reports.

Confirmed live on 2026-09-19 (pre-fix, discovery-lite phase): the query
literally proposed in the impl-plan's code sketch
(``"index_coverage verdict threshold_for universe_for artifact_degraded
degraded_inputs"``) returned `confidence: "low"`, `degraded_inputs:
["inventory.json"]`, because `c`'s 0/2 verdict is a repo-wide, sub-1%-share
minority with no bearing on the all-Python candidate slice that query's
`files_likely_to_edit` resolved to at that time.

> [!DECISION D-123-2] owner=impl-agent date=2026-09-20 refs=step-3
> That literal query no longer reaches `high` on today's live index, even with
> the KLC-123 fix correctly applied — NOT because the fix is wrong, but because
> the query's own token `"coverage"` weak-path-matches
> `tests/fixtures/rules/coverage/{sample.h,sample.cpp,sample.rs}` (added the
> SAME day, AFTER this ticket's discovery measurement, by KLC-122 step-7 commit
> `7f813a9`, dated 2026-09-19T22:17:50+03:00 — discovery-lite finished at
> 20:57:32Z). Those files score > 0 for that query (a literal path-segment
> hit), so their languages (c, cpp, rust — all repo-wide minorities) are
> HONESTLY members of `candidate_languages` per AC-6's own contract ("matched
> (score > 0) files") — the fix correctly caps in that case, per AC-6/AC-2, not
> incorrectly. The measured baseline is simply stale: index content drifted
> between discovery and build on the same day, via a sibling ticket.
> This test therefore uses a different, still index_coverage/AC-16-focused
> query — `"artifact_degraded threshold_for universe_for verdict index_health
> hook_mode"` — that avoids the incidental `"coverage"` token collision while
> preserving every invariant AC-8 actually asserts: `files_likely_to_edit` is
> entirely Python (4 of the 5 originally-named files —
> `core/skills/index_coverage.py`, `index_health.py`, `settings.py`,
> `detect_languages.py` — plus `core/skills/artefacts.py` in place of
> `callgraph_cpp.py`), top-module separation clears the `_HIGH_SEPARATION_RATIO
> = 4.0` bar (measured 6.04x live today, vs. the original 7.68x measurement —
> both comfortably above the 4.0x rule that actually governs `high`),
> `confidence` reaches `"high"`, `"inventory.json"` is absent from
> `degraded_inputs`, and `coverage_advisories` still honestly names the
> genuinely-uncovered repo-minority languages (`c`, `csharp`, `java`, `ruby`,
> each ~0.4% share) it excluded from the cap. The assertion itself
> (`confidence == "high"` and `"inventory.json" not in degraded_inputs`) is
> UNCHANGED and not weakened — only the query text and its measured secondary
> numbers (the exact edit-file list, the separation ratio) are updated to
> today's real, honestly-measured live values. See build-log.md's step-3
> entry for the full command transcript.

Skips (never fails) when the checkout has no built `.klc/index/` — the test
is a permanent regression pin, not a build-time hard requirement.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-retriever.py"
_IDX = Path(os.environ.get("PROJECT_ROOT", _FW_ROOT)) / ".klc" / "index"
_FILES = ("modules.json", "file_roles.json", "module_edges.json",
          "test_map.json", "inventory.json")


def _load_skill():
    spec = importlib.util.spec_from_file_location(
        "planning_retriever_klc123_dogfood", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(name):
    path = _IDX / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_python_only_query_reaches_high_confidence_on_live_index():
    """[!DECISION D-124-1] owner=impl-agent date=2026-09-20 refs=KLC-124-step-6

    test-plan.md's own "Regression scenarios" section for KLC-124 anticipated
    this exact edit: "its `coverage_advisories` assertion (`any("'c'" in a
    for a in trace["coverage_advisories"])`) is EXPECTED TO CHANGE MEANING
    once 'c' no longer exists as a language on this repo ... the KLC-123 test
    itself is a build-time regression check for whoever lands this ticket."
    KLC-124 fixed `EXT_LANG["h"]` from `c` to `cpp`, so this repo's live
    index (rebuilt via the direct builders, see KLC-124's build-log.md
    step-6) no longer has a `c` language at all — `coverage_advisories` can
    never again honestly name it. The remaining repo-minority languages with
    no rule-set coverage are `csharp` and `ruby` (each ~0.4% share, verified
    live post-rebuild), so the assertion now checks for one of THOSE — same
    invariant (an honest, non-capping advisory for a genuinely-uncovered
    minority language), different language, because the language that used
    to be the uncovered one no longer exists."""
    data = {name: _read(name) for name in _FILES}
    if any(v is None for v in data.values()):
        pytest.skip("no built .klc/index/ on this checkout")
    pr = _load_skill()
    # See D-123-2 above: the original discovery-measured query no longer
    # reaches "high" on today's live index because of a same-day, unrelated
    # sibling-ticket fixture addition — this query preserves every invariant
    # AC-8 actually cares about while avoiding that incidental collision.
    query = ("artifact_degraded threshold_for universe_for verdict "
             "index_health hook_mode")
    trace = pr.build_trace(
        query, "deterministic", data["modules.json"], data["file_roles.json"],
        data["module_edges.json"], data["test_map.json"], data["inventory.json"])
    assert "inventory.json" not in trace["degraded_inputs"], trace["degraded_inputs"]
    assert trace["confidence"] == "high", trace
    assert trace["files_likely_to_edit"], trace
    assert all(f.endswith(".py") for f in trace["files_likely_to_edit"]), trace
    # D-124-1: 'c' no longer exists as a language on this repo (KLC-124) —
    # 'csharp'/'ruby' are the remaining genuinely-uncovered minorities.
    assert any("'csharp'" in a or "'ruby'" in a for a in trace["coverage_advisories"]), \
        trace["coverage_advisories"]


def test_original_ac8_literal_query_reaches_high_confidence_on_live_index():
    """AC-8, [!DECISION D-123-3] owner=impl-agent date=2026-09-20 refs=step-5.

    Supersedes D-123-2's rationale for why the SPEC'S OWN LITERAL query
    ("index_coverage verdict threshold_for universe_for artifact_degraded
    degraded_inputs") could not be restored as a passing assertion. D-123-2's
    diagnosis was correct as far as it went — that query's token "coverage"
    weak-path-matches `tests/fixtures/rules/coverage/{sample.h,sample.cpp,
    sample.rs}`, so those files DO score > 0 for it. What D-123-2 did not
    anticipate is review round-1's F-1 fix (this same step): `candidate_languages`
    is now scoped to the trace's PRESENTED slices (`files_likely_to_edit` ∪
    `files_to_read_first`), not to every matched (score > 0) file. Those three
    fixture files are matched but orphaned (no module claims
    `tests/fixtures/rules/coverage/`) and never eligible_as_primary, so they
    never reach either presented slice — their languages (c, cpp, rust) no
    longer enter `candidate_languages` at all, and the literal query now
    reaches `confidence: high` on today's live index, same as D-123-2's
    substituted query. Confirmed live 2026-09-20 (see build-log.md's step-5
    entry for the full command transcript):
        confidence: high
        degraded_inputs: []
        files_likely_to_edit: ['core/skills/index_coverage.py',
            'core/skills/settings.py', 'core/skills/ac_test_coverage.py',
            'core/skills/callgraph_cpp.py', 'core/skills/callgraph_python.py']
        separation: 6.96x (>= 4.0)
    D-123-2's substituted query is kept as a second, permanent assertion
    (belt-and-suspenders against a future index drift re-introducing the
    collision for one query but not the other) — this test restores the
    spec's own literal AC-8 text as a passing assertion so a reader of
    spec.md alone no longer sees a claim with no matching test.
    """
    data = {name: _read(name) for name in _FILES}
    if any(v is None for v in data.values()):
        pytest.skip("no built .klc/index/ on this checkout")
    pr = _load_skill()
    query = ("index_coverage verdict threshold_for universe_for "
             "artifact_degraded degraded_inputs")
    trace = pr.build_trace(
        query, "deterministic", data["modules.json"], data["file_roles.json"],
        data["module_edges.json"], data["test_map.json"], data["inventory.json"])
    assert "inventory.json" not in trace["degraded_inputs"], trace["degraded_inputs"]
    assert trace["confidence"] == "high", trace
    assert trace["files_likely_to_edit"], trace
    assert all(f.endswith(".py") for f in trace["files_likely_to_edit"]), trace
