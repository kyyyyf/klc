#!/usr/bin/env python3
"""KLC-118 step-6 — AC-10: the migration sweep deletes every pre-existing
prompt card left under the ticket tree by the pre-KLC-118 layout, leaving
the state branch untouched (the files were never tracked — FACT F-006).

Also covers impl-plan-review finding F-2: the AUTOMATIC sweep invoked from
a canonical render must be scoped to the ticket AND the phase being
rendered — never the whole ticket subtree — so it cannot delete a SIBLING
phase's still-live, legitimately-degraded card (AC-12).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def _git(args, cwd, *, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=check)


def _init_repo(root: Path) -> None:
    _git(["init", "-b", "main"], root)
    _git(["config", "user.name", "t"], root)
    _git(["config", "user.email", "t@t"], root)


def test_migration_sweep_deletes_stale_ticket_dir_cards_and_leaves_the_state_branch_clean(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import artefacts
    import state_sync

    _init_repo(tmp_path)
    tk = tmp_path / ".klc" / "tickets" / "KLC-MIG1"
    (tk / "design").mkdir(parents=True)
    (tk / "build").mkdir(parents=True)
    (tk / "meta.json").write_text('{"ticket":"KLC-MIG1"}\n', encoding="utf-8")
    (tk / "design" / "_prompt.md").write_text("stale\n", encoding="utf-8")
    (tk / "build" / "_prompt_step_1.md").write_text("stale\n", encoding="utf-8")
    (tk / "build" / "_prompt_step_2.md").write_text("stale\n", encoding="utf-8")

    _git(["add", "meta.json"], tk)  # only the REAL artefact is tracked
    _git(["commit", "-m", "init"], tmp_path)

    removed = artefacts.sweep_legacy_cards()  # bare CLI-style global sweep
    assert len(removed) == 3, removed

    remaining = list((tmp_path / ".klc" / "tickets").rglob("_prompt*.md"))
    assert remaining == [], remaining

    status = _git(["status", "--porcelain"], tmp_path).stdout
    assert status.strip() == "", \
        f"deleting never-tracked cards must produce no diff: {status!r}"

    # C-002: the derived-ignore patterns are retained even though cards
    # moved off the ticket tree.
    assert "_prompt.md" in state_sync._DERIVED_IGNORES
    assert "_prompt_step_*.md" in state_sync._DERIVED_IGNORES
    assert "scratch/" in state_sync._DERIVED_IGNORES


def test_auto_sweep_is_phase_scoped_and_spares_a_sibling_phases_degraded_card(
        tmp_path, monkeypatch):
    """F-2: phase A degraded to the ticket dir earlier (its only copy);
    phase B of the SAME ticket then renders canonically. The automatic sweep
    that fires on B's canonical render must not delete A's still-live card."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import artefacts

    ticket = "KLC-MIG2"
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "review:ack", "phase_history": [], "track": "M",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    # phase A ("design") degraded earlier — its ONLY copy lives in the ticket
    # dir; the canonical location was never written.
    design_dir = tdir / "design"
    design_dir.mkdir()
    (design_dir / "_prompt.md").write_text("design degraded copy\n",
                                           encoding="utf-8")
    (tdir / "spec.md").write_text("## Goals\nfake\n", encoding="utf-8")

    # phase B ("review") renders canonically — must NOT sweep phase A's card.
    artefacts.render_card(ticket, "review", meta)

    assert (design_dir / "_prompt.md").exists(), (
        "the automatic sweep must be scoped to the phase being rendered "
        "(review), not the whole ticket subtree — it deleted a sibling "
        "phase's legitimately-degraded card")
    canonical_review = (tmp_path / ".klc" / "scratch" / ticket / "review"
                        / "_prompt.md")
    assert canonical_review.exists()


def test_sweep_cards_cli_subcommand(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tk = tmp_path / ".klc" / "tickets" / "KLC-MIG3"
    (tk / "review").mkdir(parents=True)
    (tk / "review" / "_prompt.md").write_text("stale\n", encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(FW_ROOT / "core" / "skills" / "artefacts.py"),
         "sweep-cards", "KLC-MIG3"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "PROJECT_ROOT": str(tmp_path)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tk / "review" / "_prompt.md").exists()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
