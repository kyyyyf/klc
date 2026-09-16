#!/usr/bin/env python3
"""tests/test_klc113_byte_budget.py — KLC-113 step-7 (AC-14).

Locks the shipped-prompt byte saving so it cannot silently regrow: the
measured baseline was 220,412 bytes across 25 files; the ceiling is
208,000, a reduction of at least 12,000 bytes.
"""
from __future__ import annotations

from pathlib import Path

FW = Path(__file__).resolve().parent.parent

BUDGET = 208_000  # down from the measured 220,412-byte baseline (AC-14)


def total_bytes(agents_dir: Path) -> int:
    return sum(f.stat().st_size for f in agents_dir.glob("*.md"))


def test_plugin_agents_total_bytes_under_budget() -> None:
    total = total_bytes(FW / "klc-plugin" / "agents")
    assert total <= BUDGET, (
        f"klc-plugin/agents/*.md is {total} bytes, over the {BUDGET} ceiling "
        f"(KLC-113 AC-14); the prompts regrew — shorten a shared include, "
        f"do not delete phase reasoning"
    )


def test_byte_budget_check_fails_on_oversized_fixture(tmp_path) -> None:
    """Negative twin — the same budget-check function, pointed at a fixture
    directory containing one oversized .md file, fails rather than silently
    passing."""
    big = tmp_path / "oversized.md"
    big.write_text("x" * (BUDGET + 1), encoding="utf-8")
    total = total_bytes(tmp_path)
    assert total > BUDGET, (
        "fixture must exceed the budget for this negative twin to mean anything"
    )
