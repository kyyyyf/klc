"""AC-12: the token-telemetry section of docs/process.md documents the new
attempt keys, which runs are measured vs. estimated, and how to run a
review headlessly for a measured before/after (independent of the
untracked maki review file, per KLC-137's own Q-007 pattern).
"""
from __future__ import annotations

from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
_PROCESS = FW_ROOT / "docs" / "process.md"
_FORBIDDEN = "docs/" + "20260928_from_maki.md"   # built in two parts (Q-007)


def _section() -> str:
    text = _PROCESS.read_text(encoding="utf-8")
    start = text.index("## Token telemetry & budget guard")
    nxt = text.find("\n## ", start + 1)
    return text[start: nxt if nxt != -1 else len(text)]


def test_process_md_token_telemetry_section_documents_the_new_keys():
    """AC-12: the token-telemetry section names the new attempt keys, which
    runs are measured vs. estimated (runner-dispatched headless / card
    renders, in-session agents, the hand-run external reviewer, the
    ticketless indexing agents of scripts/init.py), the `in` vs. total-input
    distinction, that `cost_usd` is never recomputed, the new calibration
    wording, and the recipe for a measured before/after review."""
    section = _section()
    for needle in (
        "cost_usd", "num_turns", "cache_write", "run_pass", "by_source",
        "measured_per_ticket", "failed", "total input", "never recomputed",
        "estimated in / provider total input", "in-session",
        "external reviewer", "indexing",
        "RUN_LOCAL_SUBAGENTS=1 REVIEW_RUNNER=scripts/review-runner.py",
    ):
        assert needle in section, f"missing {needle!r} in the token-telemetry section"


def test_docs_section_never_references_the_untracked_maki_file():
    """AC-12 (C-005, KLC-137's F-9/Q-007 pattern): the untracked maki file's
    path appears nowhere in docs/process.md or in this test file, so the
    doc test passes on a clean checkout where that file is untracked."""
    assert _FORBIDDEN not in _PROCESS.read_text(encoding="utf-8")
    assert _FORBIDDEN not in Path(__file__).read_text(encoding="utf-8")
