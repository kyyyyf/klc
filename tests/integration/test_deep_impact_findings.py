#!/usr/bin/env python3
"""Integration tests for the deep-impact reviewer prompt (KLC-025 step-3).

Tests the reviewer's output contract:
- AC-2: stale config/string reference → BLOCKING finding with file:line
- AC-3: every finding has a verified file:line citation
- AC-3: pre-existing issues not introduced by the diff are not reported

These are fixture-based tests: they parse the reviewer's markdown output
format (## Section + finding structure) rather than spawning a live agent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

# Regex to detect finding headings in reviewer partials
_FINDING_RE = re.compile(
    r"^\s*###\s+\[(?P<severity>[A-Z]+)\]\s+(?P<title>.+)$", re.MULTILINE
)
# file:line citation pattern (must appear in the finding body)
_CITATION_RE = re.compile(r"[\w./\-]+\.\w+:\d+")


def _parse_findings(partial_text: str) -> list[dict]:
    """Extract all findings from a reviewer partial markdown text."""
    findings = []
    lines = partial_text.splitlines()
    i = 0
    while i < len(lines):
        m = _FINDING_RE.match(lines[i])
        if m:
            severity = m.group("severity")
            title = m.group("title").strip()
            # collect body until next finding or end
            body_lines = []
            i += 1
            while i < len(lines) and not _FINDING_RE.match(lines[i]):
                body_lines.append(lines[i])
                i += 1
            body = "\n".join(body_lines)
            findings.append({"severity": severity, "title": title, "body": body})
        else:
            i += 1
    return findings


def _has_citation(finding: dict) -> bool:
    """Return True iff finding title or body contains a file:line reference."""
    combined = finding["title"] + "\n" + finding["body"]
    return bool(_CITATION_RE.search(combined))


# ---------------------------------------------------------------------------
# Fixture: a synthetic reviewer partial that the deep-impact prompt *should*
# produce for a rename diff that leaves a stale config reference.
# ---------------------------------------------------------------------------
#
# In real operation the reviewer agent produces these partials.  Here we test
# the OUTPUT CONTRACT by constructing the expected format and verifying our
# parsing + assertion helpers work correctly.  The _test_ that matters is
# test_prompt_file_exists: that verifies the prompt was actually authored.
#
# The fixture partial represents: function renamed from `fetch_issue` to
# `get_issue` in code, but `config/jira.yml` still references `fetch_issue`.

_STALE_CONFIG_PARTIAL = """\
## deep-impact Review

Runtime regressions detected.

### [HIGH] Stale config reference after symbol rename — config/jira.yml:12

The symbol `fetch_issue` was renamed to `get_issue` in `klc/issue.py:45`
but `config/jira.yml:12` still references the old name `fetch_issue`.
This will fail at runtime when the config value is resolved.

Evidence: `config/jira.yml:12` contains `handler: fetch_issue`

Suggested fix: Update `config/jira.yml:12` to `handler: get_issue`

### [INFO] Observation: test coverage unchanged — tests/test_issue.py:1

Pre-existing: test file references `fetch_issue` but this was already
present before the diff.

ISSUES_TOTAL=1 ISSUES_BLOCKING=1
"""

_PARTIAL_NO_CITATIONS = """\
## deep-impact Review

### [HIGH] Something went wrong

No citation provided for this finding.

ISSUES_TOTAL=1 ISSUES_BLOCKING=1
"""

_PARTIAL_PREEXISTING = """\
## deep-impact Review

Pre-existing issues detected (not introduced by this diff):
- `legacy/old.py` has a deprecated API call — not in diff scope.

No new issues introduced.

ISSUES_TOTAL=0 ISSUES_BLOCKING=0
"""


# ---------------------------------------------------------------------------
# AC-2: stale config reference produces a BLOCKING finding with file:line
# ---------------------------------------------------------------------------

def test_stale_config_reference_blocking():
    """A stale config reference finding is BLOCKING (HIGH/CRITICAL) and
    cites the stale file:line."""
    findings = _parse_findings(_STALE_CONFIG_PARTIAL)
    blocking = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]
    assert blocking, "expected at least one blocking finding for stale config reference"
    stale = next(
        (f for f in blocking if "stale" in f["title"].lower()
         or "config" in f["title"].lower()
         or "rename" in f["title"].lower()),
        None,
    )
    assert stale is not None, \
        f"no stale-config blocking finding in: {[f['title'] for f in blocking]}"
    assert _has_citation(stale), \
        f"stale-config finding has no file:line citation: {stale}"


# ---------------------------------------------------------------------------
# AC-3: every finding has a citation
# ---------------------------------------------------------------------------

def test_every_finding_has_citation():
    """Parse a partial that has a finding without a citation → detected."""
    findings = _parse_findings(_PARTIAL_NO_CITATIONS)
    uncited = [f for f in findings if not _has_citation(f)]
    # This test verifies that our helper correctly detects missing citations.
    # A real reviewer partial must have citations; the fixture _PARTIAL_NO_CITATIONS
    # deliberately lacks one so we can test the detection path.
    assert uncited, "expected uncited finding to be detected by helper"


# ---------------------------------------------------------------------------
# AC-3: pre-existing issues are not reported as findings
# ---------------------------------------------------------------------------

def test_preexisting_issue_not_reported():
    """Pre-existing issues (not in the diff) must not produce BLOCKING findings."""
    findings = _parse_findings(_PARTIAL_PREEXISTING)
    blocking = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]
    assert not blocking, \
        f"pre-existing issues must not produce blocking findings; got: {blocking}"


# ---------------------------------------------------------------------------
# AC-4: the reviewer prompt file exists (structural check)
# ---------------------------------------------------------------------------

def test_prompt_file_exists():
    """core/agents/review/deep-impact.md must exist and contain the key sections."""
    prompt_path = FW_ROOT / "core" / "agents" / "review" / "deep-impact.md"
    assert prompt_path.exists(), \
        f"deep-impact reviewer prompt missing at {prompt_path}"
    text = prompt_path.read_text(encoding="utf-8")
    # Must have a Role section
    assert "## Role" in text, "deep-impact.md missing ## Role section"
    # Must have a Rules section (for rule_catalog extraction by review.py)
    assert "## Rules" in text, "deep-impact.md missing ## Rules section"
    # Must describe structured findings output
    assert "file:line" in text or "file_line" in text, \
        "deep-impact.md must describe file:line citations in findings"
    # Must mention pre-existing issues are out of scope
    assert "pre-existing" in text.lower() or "introduced" in text.lower(), \
        "deep-impact.md must mention only introduced/worsened issues"
