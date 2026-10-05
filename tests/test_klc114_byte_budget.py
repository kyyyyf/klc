"""KLC-114 step-8 (AC-14): pins the SPECIFIC edit this ticket makes to
`core/agents/impl.md` (byte-neutral or a trim — `per-step.md` is not
rendered into `klc-plugin/agents/`, per F-104, so its Prohibitions block is
free against the budget) so a future, unrelated prompt change cannot
silently consume the byte headroom this ticket leaves untouched.
"""
from __future__ import annotations

from pathlib import Path

FW = Path(__file__).resolve().parent.parent
BUDGET = 208_000


def test_impl_and_per_step_prompt_edits_stay_within_208000_budget() -> None:
    """AC-14: the rendered agents set stays at/below budget AFTER this
    ticket's `impl.md` clarification, and the clarification's own text is
    the one actually shipped — not just an untouched byte count."""
    rendered_impl = (FW / "klc-plugin" / "agents" / "impl.md").read_text(encoding="utf-8")
    assert "build/steps.json" in rendered_impl, (
        "KLC-174's step contract (klc step verify -> build/steps.json) is "
        "missing from the REGENERATED klc-plugin/agents/impl.md — run plugin_gen.py"
    )

    total = sum(f.stat().st_size for f in (FW / "klc-plugin" / "agents").glob("*.md"))
    assert total <= BUDGET, (
        f"klc-plugin/agents/*.md is {total} bytes, over the {BUDGET} ceiling; "
        f"KLC-114's impl.md clarification must be byte-neutral or a trim"
    )
