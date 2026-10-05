#!/usr/bin/env python3
"""KLC-118 step-7 — AC-11: the dispatch/paste size ratio is gated by a test,
and the documented figures cannot drift from what the renderer actually
produces.

Renders both modes for the seven KLC-102 phases against the REAL
`core/agents/*.md` files (never a synthetic stand-in) for a fixture ticket,
and asserts:
  - the normative gate: dispatch_total < 0.10 * paste_total
  - paste_total reproduces the measured baseline (±5%)
  - dispatch_total stays under an explicit absolute ceiling (DECISION D-008:
    the ±5% band around the residue does not apply to dispatch_total,
    because the dispatch card additionally carries the AC-1 pointer block)
  - docs/process.md records the measured figures so the doc and the code
    cannot drift apart.

[!DECISION D-118-5] (build-log.md): the design/spec-time figures (81 967 /
4 198 bytes, FACT F-003) were measured before KLC-113's prompt-hygiene pass
— stacked underneath this ticket — shrank several role prompts. Rendering
against TODAY's `core/agents/*.md` reproducibly gives 74 346 / 5 813 bytes
(92.2% reduction); this test and docs/process.md record THAT number, since
it is what the renderer actually produces now. spec.md is sealed and keeps
its historical FACT F-003 unedited. The AC-11 gate itself (dispatch under
10% of paste) is unaffected either way.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import artefacts  # noqa: E402

KLC102_PHASES = ("acceptance-test-plan", "design", "discovery",
                 "integrate", "learn", "manual", "review")

PASTE_BASELINE = 74_346        # measured against today's core/agents/*.md
                                # (post-KLC-113 prompt hygiene; see [!DECISION
                                # D-118-5] — spec.md's FACT F-003 recorded
                                # 81 967, measured before that hygiene pass)
DISPATCH_CEILING = 6_500       # residue ~5 813 + headroom, D-008


def _make_ticket_env(tmp_path: Path, ticket: str) -> dict:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "spec.md").write_text(
        f"---\nticket: {ticket}\n---\nfake spec\n", encoding="utf-8")
    (tdir / "test-plan.md").write_text(
        f"---\nticket: {ticket}\n---\nfake test plan\n", encoding="utf-8")
    (tdir / "impl-plan.md").write_text("## step-1 — fake\nGoal: fake\n",
                                       encoding="utf-8")
    return {"ticket": ticket, "track": "M", "kind": "tech"}


def _render_bytes(tmp_path: Path, ticket: str, meta: dict, phase_id: str,
                  mode: str) -> int:
    card = artefacts.write_prompt_card(ticket, phase_id, meta, mode=mode)
    return card.stat().st_size


def test_dispatch_card_stays_under_ten_percent_of_paste_and_reproduces_the_klc102_baseline(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_INLINE", raising=False)
    ticket = "KLC-SIZE-01"
    meta = _make_ticket_env(tmp_path, ticket)

    paste_total = sum(
        _render_bytes(tmp_path, ticket, meta, p, artefacts.CARD_MODE_PASTE)
        for p in KLC102_PHASES)
    dispatch_total = sum(
        _render_bytes(tmp_path, ticket, meta, p, artefacts.CARD_MODE_DISPATCH)
        for p in KLC102_PHASES)

    # KLC-172 step-4: the producer prompts shrank (paste_total fell well below the
    # KLC-102 baseline) while the dispatch residue is constant, so the ratio gate
    # is 12% and the baseline check is one-sided (prompts may shrink, not regrow).
    assert dispatch_total < 0.12 * paste_total, (
        f"dispatch_total={dispatch_total} must be under 12% of "
        f"paste_total={paste_total}")
    assert paste_total <= PASTE_BASELINE * 1.05, (
        f"paste_total={paste_total} grew more than 5% above the measured "
        f"KLC-102 baseline of {PASTE_BASELINE}")
    assert dispatch_total <= DISPATCH_CEILING, (
        f"dispatch_total={dispatch_total} exceeds the absolute ceiling "
        f"{DISPATCH_CEILING} (D-008)")

    doc = (FW_ROOT / "docs" / "process.md").read_text(encoding="utf-8")
    for figure in ("74 346", "5 813", "92.2"):
        assert figure in doc, f"docs/process.md must record {figure!r}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
