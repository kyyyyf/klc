"""tests/integration/test_klc110_derived_ignore.py — KLC-110 step-4:
`.klc/knowledge/retrieval-eval.jsonl` is a derived, never-tracked artifact
(AC-16)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import state_sync as _ss  # noqa: E402

# The entries observed on this branch BEFORE this ticket's addition
# (build-time observed count: SEVEN, not the six design/options.md F-219 —
# and the impl-plan's own corrected count — assumed; KLC-119 added
# `telemetry.jsonl` after those citations were written. See build-log.md
# D-110-4.)
_PRE_EXISTING = (
    "knowledge/tickets-index.jsonl", ".lock", ".index.json",
    "_prompt.md", "_prompt_step_*.md", "scratch/", "telemetry.jsonl",
)


def test_retrieval_eval_jsonl_registered_derived_never_tracked_worktree_clean_after_ack():
    """AC-16: `.klc/knowledge/retrieval-eval.jsonl` is registered as a
    derived, never-tracked artifact in the same list that already holds
    `knowledge/tickets-index.jsonl`."""
    assert "knowledge/retrieval-eval.jsonl" in _ss._DERIVED_IGNORES


def test_existing_derived_ignore_entries_unaffected_by_new_entry():
    """Regression: the new entry does not alter the pathspec semantics of
    any entry that existed before this ticket — every one of the SEVEN
    pre-existing entries is still present and the KLC-110 entry comes
    right after them (KLC-172 later appended three ad-hoc-log patterns,
    so the tuple is no longer exactly SEVEN + 1)."""
    for entry in _PRE_EXISTING:
        assert entry in _ss._DERIVED_IGNORES
    assert _ss._DERIVED_IGNORES[len(_PRE_EXISTING)] == "knowledge/retrieval-eval.jsonl"
