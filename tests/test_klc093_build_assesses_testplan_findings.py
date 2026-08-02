"""Prompt-structural tests for KLC-093 (E-093 · build assesses test-plan-review findings).

E-093 is a PROMPT + DOCS wiring ticket: it EXTENDS the existing build-start
assessment step in `core/agents/impl.md` so it ALSO reads
`test-plan-review-findings.json` (the independent test-plan reviewer's OBJECTIVE
findings, KLC-085) and requires the implementer to assess each finding
fix/won't-fix — SYMMETRIC with the spec-review-findings handling KLC-084 already
wired. There is no new runtime code, so the acceptance signal is a set of
prompt-structural assertions that pin each added prose claim to the REAL
`test-plan-review-findings.json` file and its real schema (the epic's recurring
failure class: prompt prose promising a capability the wiring does not back).

The two finding files share ONE identical schema
(`id · category · severity · detail · ref · suggested_fix`), so the impl.md
assess logic is the same for both. `test_testplan_clause_symmetric_with_spec_review_clause`
is the anti-drift guard: it forbids the test-plan sub-block from carrying any
LESS discipline than the spec-review sub-block.
"""
from __future__ import annotations

import re
import sys

from tests.prompt_harness import _FW_ROOT

_AGENTS = _FW_ROOT / "core" / "agents"
_IMPL = _AGENTS / "impl.md"
_TEST_PLAN_REVIEWER = _AGENTS / "test-plan-reviewer.md"
_SKILLS = _FW_ROOT / "core" / "skills"
_PROCESS = _FW_ROOT / "docs" / "process.md"
_PLUGIN_IMPL = _FW_ROOT / "klc-plugin" / "agents" / "impl.md"

# The independent test-plan reviewer's findings file — the REAL file the enriched
# build prompt must name. `spec_review.record_findings` (via `testplan_review.consume`)
# writes `{kind.name}-review-findings.json`; `TEST_PLAN_REVIEW.name == "test-plan"`.
_TESTPLAN_FINDINGS_FILE = "test-plan-review-findings.json"
_SPEC_FINDINGS_FILE = "spec-review-findings.json"


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def _assessment_section(text: str) -> str:
    """The build-start «Assess the independent review findings» H2 section body,
    from its heading to just before the next H2. Empty string if the (now
    generalized) heading is absent."""
    m = re.search(
        r"(^##\s+Assess the independent review findings.*?)(?=^##\s)",
        text,
        re.S | re.M,
    )
    return m.group(1) if m else ""


def _spec_and_testplan_subblocks(text: str) -> tuple[str, str]:
    """Split the assessment section into (spec-review sub-block, test-plan-review
    sub-block) around the `test-plan-review-findings.json` file anchor so the two
    can be compared element-by-element."""
    section = _assessment_section(text)
    # Everything from the FIRST mention of the test-plan findings file to the end of
    # the section is the test-plan sub-block; what precedes it carries the
    # spec-review sub-block.
    idx = section.find(_TESTPLAN_FINDINGS_FILE)
    if idx == -1:
        return section, ""
    # Back up to the start of the line that first names the test-plan file so the
    # sub-block includes its own heading/lead-in.
    line_start = section.rfind("\n", 0, idx)
    return section[:line_start], section[line_start:]


# ---------------------------------------------------------------------------
# step-1 — impl.md build-start step also assesses test-plan-review findings
# ---------------------------------------------------------------------------

def test_impl_reads_testplan_findings_file():
    """AC-1: impl.md's build-start assessment step names
    `test-plan-review-findings.json` and instructs reading it before any code."""
    section = _assessment_section(_read(_IMPL))
    assert section, (
        "impl.md must carry a generalized «Assess the independent review findings» "
        "H2 step (spec-review + test-plan-review)"
    )
    assert _TESTPLAN_FINDINGS_FILE in section, (
        "the build-start assessment step must name test-plan-review-findings.json"
    )
    # It is read (not merely mentioned): the step tells the agent to read it.
    _, tp = _spec_and_testplan_subblocks(_read(_IMPL))
    assert "read" in tp.lower(), (
        "the test-plan sub-block must instruct READING test-plan-review-findings.json"
    )
    # Pinned to the REAL schema so the prompt cannot promise a shape the file lacks.
    for token in ("id", "category", "severity", "detail", "ref", "suggested_fix"):
        assert token in tp, f"test-plan sub-block must name the real schema field '{token}'"
    # Pinned to the REAL category vocabulary from testplan_review.TEST_PLAN_REVIEW.
    for cat in ("uncovered-ac", "weak-assertion", "missing-edge-case"):
        assert cat in tp, f"test-plan sub-block must name the real category '{cat}'"


def test_impl_requires_per_finding_fix_or_wont_fix():
    """AC-2: impl.md requires a per-finding fix/won't-fix assessment of each
    test-plan-review finding, recorded in build-log.md."""
    _, tp = _spec_and_testplan_subblocks(_read(_IMPL))
    low = tp.lower()
    assert "fix" in low and "won't-fix" in low, (
        "test-plan sub-block must require a per-finding fix / won't-fix assessment"
    )
    assert "each" in low, "the assessment is required for EACH finding"
    assert "build-log.md" in low, (
        "the per-finding assessment must be recorded in build-log.md"
    )


def test_impl_high_severity_testplan_finding_is_stop_and_ask():
    """AC-3: impl.md states that a high-severity test-plan finding neither fixed
    nor consciously waived is a stop-and-ask (a [!QUESTION] / [!CONFLICT])."""
    _, tp = _spec_and_testplan_subblocks(_read(_IMPL))
    low = tp.lower()
    assert "high" in low, "the stop-and-ask rule keys on a high-severity finding"
    assert "stop-and-ask" in low or ("stop" in low and "ask" in low), (
        "an unaddressed high-severity finding must be a stop-and-ask"
    )
    assert "[!QUESTION]" in tp or "[!CONFLICT]" in tp, (
        "stop-and-ask surfaces as a [!QUESTION] / [!CONFLICT] item"
    )


def test_impl_degrades_when_testplan_findings_absent():
    """AC-4: impl.md degrades gracefully when the file is absent — nothing to
    assess, proceed, do not fabricate findings."""
    _, tp = _spec_and_testplan_subblocks(_read(_IMPL))
    low = tp.lower()
    assert "absent" in low, "the degrade rule keys on an absent file"
    assert "nothing to assess" in low, (
        "an absent file means nothing to assess"
    )
    assert "not fabricate" in low or "do not fabricate" in low, (
        "the degrade path must NOT fabricate findings"
    )


def test_testplan_clause_symmetric_with_spec_review_clause():
    """AC-5: the test-plan-review assessment clause carries every discipline element
    the spec-review clause carries, so the two cannot drift apart. Identical schema
    → identical assess logic; the test-plan block must not be weaker."""
    spec, tp = _spec_and_testplan_subblocks(_read(_IMPL))
    assert spec and tp, "both the spec-review and test-plan-review sub-blocks must exist"
    # Every load-bearing element present in the spec-review clause must also appear
    # in the test-plan-review clause. Case-insensitive, symbol-exact for the markers.
    elements = (
        "fix",              # fix assessment
        "won't-fix",        # won't-fix assessment
        "build-log.md",     # recorded where
        "high",             # high-severity trigger
        "[!question]",      # stop-and-ask marker
        "[!conflict]",      # stop-and-ask marker
        "absent",           # degrade trigger
        "fabricate",        # do-not-fabricate degrade guard
        "suggested_fix",    # schema field
    )
    spec_low, tp_low = spec.lower(), tp.lower()
    for el in elements:
        if el in spec_low:
            assert el in tp_low, (
                f"the test-plan-review clause is missing '{el}' that the spec-review "
                f"clause carries — the two must not drift apart (AC-5)"
            )


# ---------------------------------------------------------------------------
# step-2 — docs name build-time assessment of test-plan-review findings
# ---------------------------------------------------------------------------

def test_docs_name_build_assessment_of_testplan_findings():
    """AC-6: docs/process.md AND core/agents/test-plan-reviewer.md state that the
    build agent (core/agents/impl.md) reads and assesses
    test-plan-review-findings.json at build — the prompt/doc-honesty gap is closed."""
    process = _read(_PROCESS)
    reviewer = _read(_TEST_PLAN_REVIEWER)

    # process.md: names the test-plan findings file in a build-assessment context
    # (the build agent reads it and assesses each finding).
    assert _TESTPLAN_FINDINGS_FILE in process, (
        "docs/process.md must name test-plan-review-findings.json"
    )
    process_low = process.lower()
    assert "impl.md" in process_low, (
        "docs/process.md must name the build agent (core/agents/impl.md) as the consumer"
    )
    assert "build" in process_low and "assess" in process_low, (
        "docs/process.md must state the build agent ASSESSES the findings"
    )

    # test-plan-reviewer.md: makes its «to be assessed at build» promise concrete by
    # naming the build agent / impl.md that reads test-plan-review-findings.json.
    reviewer_low = reviewer.lower()
    assert "impl.md" in reviewer_low, (
        "test-plan-reviewer.md must name the build agent (core/agents/impl.md) "
        "that assesses its findings — making «assessed at build» concrete"
    )
    assert _TESTPLAN_FINDINGS_FILE in reviewer, (
        "test-plan-reviewer.md must name the test-plan-review-findings.json file "
        "the build agent reads"
    )


# ---------------------------------------------------------------------------
# step-3 — the deployed klc-plugin/agents/impl.md serves the enriched prompt
# ---------------------------------------------------------------------------

def test_plugin_impl_in_sync(tmp_path):
    """AC-7 (C-003): the deployed `klc-plugin/agents/impl.md` equals what
    `plugin_gen.generate_agents` produces from the enriched core source.
    `phase_resolver` serves the PLUGIN copy, so a stale copy means the build
    enrichment never runs — the KLC-090/092 deployment lesson.

    Scoped to `impl.md` only (the KLC-091 `test_plugin_design_in_sync` precedent);
    the byte-exact whole-tree parity across every agent is owned by the KLC-092
    guard `tests/test_plugin_agents_in_sync.py`."""
    sys.path.insert(0, str(_SKILLS))
    from plugin_gen import generate_agents

    generate_agents(output_dir=tmp_path)
    expected = (tmp_path / "impl.md").read_text(encoding="utf-8")
    committed = _PLUGIN_IMPL.read_text(encoding="utf-8")
    assert committed == expected, (
        "klc-plugin/agents/impl.md is out of sync with core/agents/impl.md — "
        "run `python3 core/skills/plugin_gen.py`"
    )
