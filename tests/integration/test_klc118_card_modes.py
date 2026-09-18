#!/usr/bin/env python3
"""KLC-118 step-3 — AC-1 / AC-2: the card writer gains a render mode.

`mode="dispatch"` omits the role-prompt body (the subagent definition already
carries it) and instead names the role-prompt file by absolute path.
`mode="paste"` (the default, and `KLC_CARD_INLINE=1`) stays byte-identical to
today's fully-inlined renderer — proven with golden files frozen BEFORE this
step's change (steps 1-2 only moved the card's location, never a byte of its
content).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import artefacts  # noqa: E402

GOLDEN_DIR = FW_ROOT / "tests" / "fixtures" / "klc118" / "golden"


def _make_ticket_env(tmp_path: Path, ticket: str, *, spec: bool = True,
                     test_plan: bool = True) -> dict:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    if spec:
        (tdir / "spec.md").write_text(
            f"---\nticket: {ticket}\n---\nfake spec\n", encoding="utf-8")
    if test_plan:
        (tdir / "test-plan.md").write_text(
            f"---\nticket: {ticket}\n---\nfake test plan\n", encoding="utf-8")
    return {"ticket": ticket, "track": "M", "kind": "tech"}


def _with_env(tmp_path: Path, extra: dict | None = None):
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(tmp_path)
    env.pop("KLC_CARD_INLINE", None)
    env.pop("KLC_CARD_ROOT", None)
    if extra:
        env.update(extra)
    return env


# --- AC-1: dispatch mode omits the role prompt, names the file -------------- #

def test_dispatch_card_omits_role_prompt_lines_and_names_the_file(tmp_path,
                                                                   monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_INLINE", raising=False)
    ticket = "KLC-DISP-01"
    meta = _make_ticket_env(tmp_path, ticket)

    role_prompt_path = FW_ROOT / "core" / "agents" / "review.md"
    assert role_prompt_path.exists()

    card = artefacts.write_prompt_card(
        ticket, "review", meta, mode=artefacts.CARD_MODE_DISPATCH)
    content = card.read_text(encoding="utf-8")

    # review-fix (MEDIUM): exempt only the SPECIFIC heading string(s) the
    # dispatch card's own fixed template coincidentally shares with role
    # prompts by convention — not every markdown heading. Before this fix
    # `^#+\s` exempted every heading in every role prompt, which would have
    # silently swallowed a real leak of a substantive heading like
    # "## Hard rules" (design.md) once KLC-112 makes the dispatch body quote
    # role-prompt fragments. "## Inputs" is the one collision D-118-2 names:
    # the card template's own "## Inputs you should read" contains it as a
    # substring.
    KNOWN_HEADING_COLLISIONS = {"## Inputs"}
    for line in role_prompt_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if len(stripped) < 8:
            continue
        if stripped in KNOWN_HEADING_COLLISIONS:
            continue
        assert stripped not in content, (
            f"dispatch card leaked a role-prompt line: {stripped!r}")

    assert str(role_prompt_path.resolve()) in content, \
        "dispatch card must still name the role-prompt file by absolute path"

    # Fail-closed companion: a missing role-prompt file still renders in
    # dispatch mode without ever falling back to embedding a body. Exercised
    # directly against the internal block-builder (a stand-in phase object)
    # rather than mutating the shared, process-cached Phase registry.
    import types
    fake_phase = types.SimpleNamespace(prompt="core/agents/does-not-exist.md")
    block = artefacts._role_prompt_block(fake_phase, artefacts.CARD_MODE_DISPATCH)
    assert "does-not-exist.md" in block
    assert "## Role prompt" in block
    assert "_MISSING" not in block, \
        "dispatch mode must point at the file, never fall back to an embedded body"


def test_dispatch_mode_on_a_checklist_phase_renders_without_a_role_prompt_path(
        tmp_path, monkeypatch):
    """Edge case (test-plan): a checklist phase (no phase.prompt) has nothing
    to strip — its dispatch card renders without raising and without naming a
    nonexistent role-prompt path."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-DISP-02"
    meta = _make_ticket_env(tmp_path, ticket)
    card = artefacts.write_prompt_card(
        ticket, "integrate", meta, mode=artefacts.CARD_MODE_DISPATCH)
    content = card.read_text(encoding="utf-8")
    assert "Integration checklist" in content


# --- AC-2: paste mode is byte-frozen ----------------------------------------- #

def test_paste_card_matches_golden_bytes_for_agent_and_checklist_phase(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_INLINE", raising=False)
    ticket = "KLC-118-GOLD"
    meta = _make_ticket_env(tmp_path, ticket)

    design_card = artefacts.write_prompt_card(
        ticket, "design", meta, mode=artefacts.CARD_MODE_PASTE)
    golden_design = (GOLDEN_DIR / "design_prompt.md").read_bytes()
    assert design_card.read_bytes() == golden_design

    integrate_card = artefacts.write_prompt_card(
        ticket, "integrate", meta, mode=artefacts.CARD_MODE_PASTE)
    golden_integrate = (GOLDEN_DIR / "integrate_prompt.md").read_bytes()
    assert integrate_card.read_bytes() == golden_integrate

    # KLC_CARD_INLINE=1 is an alternate spelling of mode="paste" (mirrors the
    # existing write_step_card precedent).
    monkeypatch.setenv("KLC_CARD_INLINE", "1")
    design_card2 = artefacts.write_prompt_card(
        ticket, "design", meta, mode=artefacts.CARD_MODE_DISPATCH)
    assert design_card2.read_bytes() == golden_design


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
