#!/usr/bin/env python3
"""KLC-119 step-3 — AC-7: one named deterministic estimator
(`budget_guard.estimate_tokens`) is shared by every caller that converts
prompt size to tokens; exactly one such rule exists in `core/`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import budget_guard  # noqa: E402


def test_same_text_yields_identical_token_count_through_card_renderer_step_brief_runner_and_budget_check(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import runner
    import artefacts

    text = "hello world " * 200 + "юникод текст ☃"
    expected = budget_guard.estimate_tokens(text)

    # runner.py's pre-dispatch guard: the SAME function object, not a
    # re-implementation (D-006).
    assert runner._estimate_tokens is budget_guard.estimate_tokens
    assert runner._estimate_tokens(text) == expected

    # the budget check consumes exactly the number estimate_tokens produced,
    # unmodified.
    verdict = budget_guard.check_prompt_budget(
        "M", budget_guard.estimate_tokens(text))
    assert verdict.estimated == expected

    # task_brief's step-brief measurement (core/phases/task_brief.py) calls
    # the shared function over the brief text, not a private rule.
    tb_source = (FW_ROOT / "core" / "phases" / "task_brief.py").read_text(
        encoding="utf-8")
    assert "budget_guard.estimate_tokens" in tb_source

    # the card renderer measures through the identical rule: render a real
    # card and compare its est_tokens against estimate_tokens over the
    # card's OWN rendered text.
    ticket = "KLC-EST1"
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "review:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    render = artefacts.render_card(ticket, "review", meta)
    card_text = render.path.read_text(encoding="utf-8")
    assert render.est_tokens == budget_guard.estimate_tokens(card_text)


def test_no_second_bytes_or_chars_to_token_rule_exists_in_source_tree():
    hits = budget_guard.find_second_estimators(FW_ROOT)
    assert hits == [], (
        f"a second size-to-token rule was found outside budget_guard.py: "
        f"{hits} — estimate_tokens must remain the ONE rule (AC-7)"
    )


def test_second_estimator_check_fails_for_a_fixture_duplicate_under_scripts(tmp_path):
    """KLC-120 review-fix MEDIUM: the scan also covers scripts/ (widened
    after scripts/review-runner.py grew its own hand-rolled `// 4` copy,
    caught only because AC-3's implementation review found it, not this
    gate) — the gate must actually bite there, not just under core/."""
    fake_root = tmp_path / "fake_repo"
    fake_scripts = fake_root / "scripts"
    fake_scripts.mkdir(parents=True)
    duplicate = fake_scripts / "sneaky_estimator.py"
    duplicate.write_text(
        "def bad(n: int) -> int:\n"
        "    return max(1, n // 4)\n",
        encoding="utf-8",
    )
    hits = budget_guard.find_second_estimators(fake_root)
    assert any(p.name == "sneaky_estimator.py" for p in hits), (
        "the estimator scan failed to catch a fixture duplicate under "
        "scripts/ — the gate is vacuous there"
    )


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
