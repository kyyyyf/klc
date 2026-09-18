#!/usr/bin/env python3
"""KLC-118 step-6 — AC-9: prompt cards are excluded from the ticket artefact
universe. A re-render can no longer dirty the pre-merge consistency
snapshot (cards moved off the hashed tree in step-1 already), and the
retrospective role prompt declares cards out of scope.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def _seed(tmp_path: Path, ticket: str) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "review:ack", "phase_history": [], "track": "M",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    (tdir / "spec.md").write_text("## Goals\nfake\n", encoding="utf-8")
    return tdir


def test_pre_merge_snapshot_excludes_cards_and_retrospective_declares_them_out_of_scope(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import consistency_check
    import artefacts

    ticket = "KLC-UNI1"
    tdir = _seed(tmp_path, ticket)
    meta = json.loads((tdir / "meta.json").read_text())

    # First render establishes the ticket's normal post-dispatch state
    # (including the metrics.tokens.<phase> entry AC-5 adds) — THIS is the
    # snapshot a pre-merge gate would actually see. The idempotency claim
    # under test is about a SUBSEQUENT re-render (autorunner._card_path
    # re-renders on every dispatch), not about the very first one.
    artefacts.render_card(ticket, "review", meta)
    before = consistency_check._hash_artefacts(ticket)
    assert not any("_prompt" in k for k in before), before

    artefacts.render_card(ticket, "review", meta)
    after = consistency_check._hash_artefacts(ticket)

    assert after == before, \
        "re-rendering a card must not change the pre-merge snapshot"
    assert not any("_prompt" in k for k in after), after


def test_retrospective_declares_prompt_cards_derived_and_out_of_scope():
    text = (FW_ROOT / "core" / "agents" / "retrospective.md").read_text(
        encoding="utf-8")
    assert re.search(
        r"[Pp]rompt\s+cards.{0,80}(DERIVED|derived).{0,150}not\s+part\s+of\s+"
        r"the\s+artefact\s+set",
        text, re.DOTALL), (
        "retrospective.md must declare prompt cards derived and out of the "
        "artefact set it reads")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
