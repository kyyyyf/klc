#!/usr/bin/env python3
"""KLC-118 step-2 — AC-7 / AC-12: the card root follows `KLC_CARD_ROOT`, a
malformed override is treated as unset, and a root that cannot be written
degrades to the ticket directory with a warning instead of failing the
phase transition.

The full next/step/dispatch cycle test gains its `dispatch`-mode render leg
in step-3 (no dispatch mode exists yet); this step covers the `klc next`
(phase card) and `klc step` (build step card) legs.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"
SKILLS_DIR = FW_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS_DIR))
sys.path.insert(0, str(FW_ROOT))


def _seed(tmp_path: Path, ticket: str, *, phase: str, track: str = "M",
          **extra) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    meta.update(extra)
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    (tdir / "spec.md").write_text(
        "## Goals\nfake\n## Acceptance Criteria\n- AC-1\n", encoding="utf-8")
    (tdir / "impl-plan.md").write_text(
        "## step-1 — fake\nGoal: fake\n\n## step-2 — fake2\nGoal: fake2\n",
        encoding="utf-8")


def _run(argv: list[str], env: dict) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(KLC), *argv],
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def test_full_next_step_dispatch_cycle_leaves_no_prompt_cards_under_the_ticket_dir(
        tmp_path, monkeypatch):
    """AC-7: after a `klc next` (phase card) + `klc step` (build step card) +
    a `/klc:run`-style dispatch-mode render, no `_prompt*.md` file exists
    under the ticket directory — every card lives at the scratch root
    instead. Repeated with `KLC_CARD_ROOT` pointed at a distinct override
    directory."""
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("KLC_CARD_ROOT", None)
    _seed(tmp_path, "KLC-CYC1", phase="design:ack", track="M")

    rc, out = _run(["next", "KLC-CYC1"], env)
    assert rc == 0, out
    rc, out = _run(["step", "KLC-CYC1", "2"], env)
    assert rc == 0, out

    # the dispatch-mode render (what `/klc:run` does right before Task(...))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    import artefacts
    dispatch_meta = {"ticket": "KLC-CYC1", "track": "M", "kind": "tech"}
    artefacts.write_prompt_card("KLC-CYC1", "design", dispatch_meta,
                                mode=artefacts.CARD_MODE_DISPATCH)

    tdir = tmp_path / ".klc" / "tickets" / "KLC-CYC1"
    assert list(tdir.rglob("_prompt*.md")) == [], \
        f"cards leaked into the ticket dir: {list(tdir.rglob('_prompt*.md'))}"
    scratch_root = tmp_path / ".klc" / "scratch" / "KLC-CYC1"
    assert (scratch_root / "build" / "_prompt_step_1.md").exists()
    assert (scratch_root / "build" / "_prompt_step_2.md").exists()
    assert (scratch_root / "design" / "_prompt.md").exists()

    # --- repeat with KLC_CARD_ROOT overridden -------------------------------
    override = tmp_path / "override"
    env2 = {**env, "KLC_CARD_ROOT": str(override)}
    _seed(tmp_path, "KLC-CYC2", phase="design:ack", track="M")
    rc, out = _run(["next", "KLC-CYC2"], env2)
    assert rc == 0, out
    rc, out = _run(["step", "KLC-CYC2", "2"], env2)
    assert rc == 0, out

    tdir2 = tmp_path / ".klc" / "tickets" / "KLC-CYC2"
    assert list(tdir2.rglob("_prompt*.md")) == []
    assert (override / "KLC-CYC2" / "build" / "_prompt_step_1.md").exists()
    assert (override / "KLC-CYC2" / "build" / "_prompt_step_2.md").exists()


def test_read_only_scratch_root_degrades_to_the_ticket_dir_without_failing_the_phase(
        tmp_path, monkeypatch):
    """AC-12: a scratch root that cannot be written degrades to the ticket
    directory with a warning, rather than raising, and stays fast even on
    the largest role prompt in the repository (discovery.md)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    readonly = tmp_path / "readonly-root"
    readonly.mkdir()
    readonly.chmod(0o400)
    monkeypatch.setenv("KLC_CARD_ROOT", str(readonly))
    try:
        import artefacts
        import importlib
        importlib.reload(artefacts)

        ticket = "KLC-RO1"
        tdir = tmp_path / ".klc" / "tickets" / ticket
        tdir.mkdir(parents=True)
        meta = {"ticket": ticket, "kind": "tech", "kind_source": "user",
                "phase": "discovery:work", "phase_history": [], "track": "M",
                "affected_modules": [], "estimate": None, "layer": "code",
                "jira_url": None, "created": "2026-01-01T00:00:00Z"}
        (tdir / "meta.json").write_text(json.dumps(meta) + "\n",
                                        encoding="utf-8")

        start = time.perf_counter()
        card = artefacts.write_prompt_card(ticket, "discovery", meta)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"render took {elapsed}s — must be well under 1s"
        assert str(card).startswith(str(tdir)), \
            f"a degraded render must fall back under the ticket dir, got {card}"
        assert card.exists()
        assert "discovery" in card.read_text(encoding="utf-8").lower()
    finally:
        readonly.chmod(0o700)


def test_malformed_card_root_override_falls_back_to_the_default_root(
        tmp_path, monkeypatch):
    """A blank/whitespace-only KLC_CARD_ROOT is treated as unset — default
    behaviour, no error (spec Failure modes)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KLC_CARD_ROOT", "   ")
    from core.shared.paths import klc_card_root
    assert klc_card_root() == tmp_path / ".klc" / "scratch"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
