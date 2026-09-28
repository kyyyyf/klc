"""KLC-114 step-8: core/agents/review/per-step.md forbids every git-write,
working-tree-cleaning and checkout/stash command, and every file write
outside its findings sink (AC-10)."""
from __future__ import annotations

from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
_PER_STEP_PROMPT = _FW_ROOT / "core" / "agents" / "review" / "per-step.md"

_REQUIRED_GIT_PHRASES = (
    "git commit", "git add", "git push", "git checkout", "git switch",
    "git restore", "git stash", "git clean", "git reset", "git rebase", "git merge",
)


def _missing_prohibitions(text: str) -> list[str]:
    """The AC-10 prohibitions not present in *text*: every named git-write
    verb, a working-tree-modification prohibition, and a named findings
    sink limiting file writes."""
    missing = [p for p in _REQUIRED_GIT_PHRASES if p not in text]
    if "working tree" not in text.lower():
        missing.append("working tree")
    if "findings.json" not in text:
        missing.append("findings.json (the findings sink)")
    return missing


def test_per_step_prompt_forbids_git_write_working_tree_and_stray_file_writes():
    """AC-10: the prompt-hygiene check finds every required prohibition
    already present in the real per-step.md."""
    text = _PER_STEP_PROMPT.read_text(encoding="utf-8")
    assert _missing_prohibitions(text) == []


def test_hygiene_check_fails_when_a_prohibition_is_missing():
    """AC-10 gate-bites twin: a synthetic copy of the prompt with one
    prohibition phrase deleted is reported missing — the presence assertion
    cannot pass vacuously on any text."""
    text = _PER_STEP_PROMPT.read_text(encoding="utf-8")
    broken = text.replace("git checkout", "")
    missing = _missing_prohibitions(broken)
    assert "git checkout" in missing
