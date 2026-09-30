"""AC-13: the repository holds the captured headless envelope fixtures.

Step-1 of KLC-133 (operator gate): the operator captured one real
single-object envelope and one real ``--verbose`` run that started a
background subagent; this module derives the other two fixtures from them
and records their provenance. Every other klc133 test module reads these
fixtures rather than launching the real CLI (C-004).
"""
from __future__ import annotations

import os
import shutil

from _klc133_support import (  # noqa: E402
    FORBIDDEN_PATTERNS,
    fixture_json,
    fixture_text,
    forbidden_hits,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)


def test_fixtures_exist_for_all_four_named_shapes_with_a_readme_provenance_line() -> None:
    """AC-13: all four named fixture shapes exist, parse, and are named in the README."""
    readme = fixture_text("README.md")
    for name in (
        "envelope-single.json",
        "envelope-multiturn-cache.json",
        "envelope-is-error.json",
        "envelope-verbose-subagent.json",
    ):
        envelope = fixture_json(name)  # exists and parses as JSON
        assert envelope is not None
        matches = [
            line for line in readme.splitlines()
            if name in line and ("captured" in line or "derived" in line)
        ]
        assert matches, f"{name} has no captured/derived provenance line in the README"


def test_readme_records_the_usage_source_finding_of_the_subagent_run() -> None:
    """AC-13: the README states Q-009's usage-source finding and its subagent evidence."""
    readme = fixture_text("README.md")
    usage_source_lines = [
        line for line in readme.splitlines() if line.startswith("usage-source:")
    ]
    assert len(usage_source_lines) == 1
    assert usage_source_lines[0].strip() in (
        "usage-source: usage",
        "usage-source: modelUsage",
    )

    verbose = fixture_json("envelope-verbose-subagent.json")
    has_subagent_message = any(
        isinstance(message, dict) and isinstance(message.get("parent_tool_use_id"), str)
        and message["parent_tool_use_id"]
        for message in verbose
    )
    if not has_subagent_message:
        # impl-plan.md step-1: when no message carries a parent_tool_use_id,
        # the README records that absence and the Q-009 decision rests on
        # the modelUsage comparison alone (D-116).
        assert "subagent-messages: absent" in readme


def test_multiturn_fixture_has_several_turns_cache_reads_and_cache_writes() -> None:
    """AC-13: the multi-turn fixture has several turns plus cache reads and writes."""
    envelope = fixture_json("envelope-multiturn-cache.json")
    assert envelope["num_turns"] > 1
    assert envelope["usage"]["cache_read_input_tokens"] > 0
    assert envelope["usage"]["cache_creation_input_tokens"] > 0


def test_derived_fixtures_keep_the_key_set_of_the_captured_envelope() -> None:
    """AC-13: each derived fixture keeps the key set of the captured object it came from."""
    single = fixture_json("envelope-single.json")
    verbose = fixture_json("envelope-verbose-subagent.json")
    results = [
        message for message in verbose
        if isinstance(message, dict) and message.get("type") == "result"
    ]
    assert len(results) >= 2, "the verbose fixture must hold at least two result elements"
    # D-116 (impl-plan.md): the multi-turn fixture is derived from the earlier
    # of the two captured result elements, not the last — the last one's own
    # num_turns is 1, which does not exercise a multi-turn envelope.
    source = results[0]

    multiturn = fixture_json("envelope-multiturn-cache.json")
    assert set(multiturn.keys()) == set(source.keys())
    assert set(multiturn["usage"].keys()) == set(source["usage"].keys())

    is_error = fixture_json("envelope-is-error.json")
    assert set(is_error.keys()) == set(single.keys())
    assert set(is_error["usage"].keys()) == set(single["usage"].keys())


def test_claude_cli_env_var_points_at_a_missing_binary_for_the_whole_module() -> None:
    """AC-13: pin — the hermetic fixture points CLAUDE_CLI at a binary not on PATH."""
    assert shutil.which(os.environ["CLAUDE_CLI"]) is None
    import runner  # noqa: E402  (sys.path set up by _klc133_support)

    rc, stdout, stderr = runner._dispatch_anthropic(None, "hi", 5, {})
    assert rc == 2
    assert "not on PATH" in stderr


# --- step-10 review-fix (AC-13, code-review MEDIUM + external LOW) ----------
# the step-1 redaction only scrubbed top-level session_id/uuid/parent_uuid/
# request_id/cwd; it missed the free-text tool_result content and the
# msg_/toolu_ ids embedded inside message bodies (both LOW/MEDIUM findings
# on envelope-verbose-subagent.json). This is the fixture-level regression
# gate: it must fail loudly if any committed fixture ever regains one of
# these patterns, not just prove today's file is clean by inspection.
#
# KLC-127 step-6: FORBIDDEN_PATTERNS and forbidden_hits() moved to
# _klc133_support.py so tests/fixtures/klc127-replay/ can share the same
# gate (AC-30) instead of re-implementing it. This module keeps only the
# README exemption, which is specific to these envelope fixtures.

_FIXTURE_FILES = (
    "envelope-single.json", "envelope-multiturn-cache.json",
    "envelope-is-error.json", "envelope-verbose-subagent.json", "README.md",
)

_README_EXEMPT_LABELS = (
    "a /tmp/ path", "a /home/ path",
    "the word 'signature' outside the redacted placeholder line",
)


def test_committed_fixtures_carry_no_leaked_identifier_or_local_path() -> None:
    """AC-13/KLC-165: grep every committed fixture (and the README) for a
    /tmp/ or /home/ path, a real msg_/toolu_ id, a UUID, 'signature', any
    configured private redaction term (KLC-165) or an '@' — none may remain
    other than this ticket's own fixed redaction placeholders (the zero
    UUID and the one documented `"signature": "REDACTED-SIG"` line, whose
    key name is structural, not sensitive)."""
    assert FORBIDDEN_PATTERNS  # the shared gate is non-empty (import sanity)
    for name in _FIXTURE_FILES:
        hits = forbidden_hits(fixture_text(name))
        if name == "README.md":
            # The README's own prose NAMES these patterns descriptively
            # (documenting what was redacted from the JSON fixtures) —
            # that is not a leak. The JSON envelope files themselves are
            # still checked below (they must hold no real path at all).
            hits = [h for h in hits if h not in _README_EXEMPT_LABELS]
        assert hits == [], f"{name}: found {hits}"
