#!/usr/bin/env python3
"""tests/test_klc113_prompt_honesty.py — KLC-113 prompt-honesty checker.

Step-4 (AC-9): a literal-string regression over the five recorded misses in
spec.md's FACT block — `test_known_misses_are_resolved`.

Step-5 (AC-6, AC-7, AC-8, AC-10, AC-9's real-tree arm) adds the mechanical
checker `core/skills/prompt_honesty.py` and its positive/negative arms.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW))

AGENTS_DIR = FW / "core" / "agents"

# D-006: the generic path-shaped scanner (step-5) cannot see bare-word
# references like `verifier` or the `validator.md` sentence, so those two
# misses are pinned here by literal string, not by the scanner.
GONE = {
    "core/agents/test-planner.md":         ["test-framework.json", "symbols_by_module.json"],
    "core/agents/test.md":                 ["test-framework.json"],
    "core/agents/review/test-coverage.md": ["test-framework.json"],
    "core/agents/discovery.md":            ["validator.md", ".klc/config/discovery.yml"],
    "core/agents/impl.md":                 ["verifier", "symbols_by_module.json"],
    "core/agents/design.md":               ["verifier"],
    "core/agents/decompose.md":            ["symbols_by_module.json"],
    "core/agents/docgen.md":               ["symbols_by_module.json"],
}


def test_known_misses_are_resolved() -> None:
    hits = [
        f"{rel}: {tok}"
        for rel, toks in GONE.items()
        for tok in toks if tok in (FW / rel).read_text(encoding="utf-8")
    ]
    assert hits == [], hits


# --- step-5: AC-6, AC-7, AC-8, AC-10, AC-9's real-tree arm ---------------------

import prompt_honesty as ph  # noqa: E402


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_allowlist_entry_without_producer_rejected() -> None:
    """AC-8 negative twin — a producer-less allowlist entry cannot be added
    silently; the constructor itself rejects it."""
    try:
        ph.AllowlistEntry(".klc/index/whatever.json", "")
    except ValueError:
        pass
    else:
        raise AssertionError("AllowlistEntry should reject an empty producer")
    try:
        ph.AllowlistEntry(".klc/index/whatever.json", "   ")
    except ValueError:
        pass
    else:
        raise AssertionError("AllowlistEntry should reject a blank producer")


def test_fake_path_in_fixture_prompt_fails(tmp_path) -> None:
    """AC-6 negative twin — a fabricated path in a fixture prompt directory
    (not the real tree) is rejected by the same public entry point."""
    _write(tmp_path / "fixture-phase.md",
           "Read `.klc/index/totally-fabricated-artifact.json` before starting.\n")
    misses = ph.scan(roots=[tmp_path])
    assert any("totally-fabricated-artifact.json" in m for m in misses), misses


def test_all_backticked_references_resolve() -> None:
    """AC-6 — every backticked core/scripts/.klc/docs reference in the real,
    post-ticket core/agents/*.md tree resolves (exists, normalises to an
    existing module file, or is allowlisted with a producer)."""
    misses = ph.scan()
    # Keep this arm focused on path resolution: filter out verb/skill misses,
    # which have their own dedicated tests below.
    path_misses = [m for m in misses if "unresolved reference" in m]
    assert path_misses == [], path_misses


def test_klc_verb_mentions_resolve_against_dispatcher() -> None:
    verbs = ph.klc_verbs()
    # D-007: reindex is deliberately absent from LIFECYCLE_CMDS/OPERATIONAL_CMDS
    # and served by an explicit `scripts/klc` handler — reading only the two
    # tuples would wrongly report `klc reindex` as unknown.
    assert "reindex" in verbs
    assert "ack" in verbs and "step" in verbs and "task-brief" in verbs
    misses = ph.scan()
    verb_misses = [m for m in misses if "unknown klc verb" in m]
    assert verb_misses == [], verb_misses


def test_skill_invocation_mentions_resolve_to_existing_files() -> None:
    misses = ph.scan()
    skill_misses = [m for m in misses if "skill invocation" in m]
    assert skill_misses == [], skill_misses


def test_allowlist_index_artifacts_pass_by_producer() -> None:
    named = {
        ".klc/index/inventory.json", ".klc/index/inventory-hash.json",
        ".klc/index/module_edges.json", ".klc/index/symbol_usage.json",
        ".klc/index/test_map.json",
    }
    for pattern in named:
        entry = ph._allowed(pattern)
        assert entry is not None, pattern
        assert entry.producer.strip(), pattern
    # a <KEY>-scoped ticket artifact passes the same way
    assert ph._allowed(".klc/tickets/<KEY>/spec.md") is not None


def test_prompt_honesty_green_on_shipped_tree() -> None:
    """AC-9's second enforcement arm — the mechanical scanner is green on the
    real, post-ticket tree (the literal-string arm is test_known_misses_are_resolved
    above; D-006 — the scanner cannot see bare-word misses like `verifier`)."""
    assert ph.scan() == []


def test_fabricated_review_reviewer_path_is_reported_as_a_miss(tmp_path) -> None:
    """review-fix (MEDIUM): the `core/agents/review/*` allowlist entry was
    narrowed to the exact placeholder `core/agents/review/<reviewer>.md`
    (retrospective.md's only real reference) — a FABRICATED, non-placeholder
    path under that same directory must still be caught by the scanner,
    exactly as every other directory already is. Before the fix the wildcard
    silently admitted this path (verified live: `ph._allowed(...)` returned
    a match and `scan()` reported no miss)."""
    assert ph._allowed("core/agents/review/does-not-exist.md") is None
    _write(tmp_path / "fixture-phase.md",
           "See `core/agents/review/does-not-exist.md` for the reviewer prompt.\n")
    misses = ph.scan(roots=[tmp_path])
    assert any("does-not-exist.md" in m for m in misses), misses
    # the real placeholder reference itself must still resolve.
    assert ph._allowed("core/agents/review/<reviewer>.md") is not None


def test_review_subdir_included_in_scan() -> None:
    """Q-003 — the scan glob widens to core/agents/review/*.md, which
    generate_agents itself does not descend into."""
    files = ph._prompt_files()
    assert any(f.name == "test-coverage.md" and "review" in str(f) for f in files)


def test_negative_arm_reports_injected_fake_path_and_verb(tmp_path) -> None:
    """AC-10 — mirrors test_guard_names_drifted_and_missing_files: a mutated
    prompt copy naming one fabricated path and one fabricated klc verb is
    reported by name, not just a boolean fail."""
    _write(tmp_path / "mutated.md",
           "Read `.klc/index/does-not-exist-either.json` then run `klc frobnicate <KEY>`.\n")
    misses = ph.scan(roots=[tmp_path])
    assert any("does-not-exist-either.json" in m for m in misses), misses
    assert any("frobnicate" in m for m in misses), misses
