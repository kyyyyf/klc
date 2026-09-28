#!/usr/bin/env python3
"""KLC-120 step-2 — AC-10: `scripts/review.py`'s `_should_run_external`
applies the API-key check only when the resolved provider is `openai` or
`google`; for the `anthropic` route it checks the `claude` CLI on PATH
instead, skipping with the stated reason "claude CLI not on PATH" when
absent. All cases run with neither ANTHROPIC_API_KEY nor OPENAI_API_KEY in
the environment (F-019: this project's real host has no provider key and
the claude CLI on PATH)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import review_plan  # noqa: E402


def _clear_keys(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _stub_claude_on_path(tmp_path: Path, monkeypatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return stub


def _empty_path(tmp_path: Path, monkeypatch) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))


def test_should_run_external_anthropic_route_runs_with_fake_claude_cli_on_path_and_no_api_keys(
        tmp_path, monkeypatch):
    """AC-10 positive: a fake `claude` on PATH, no API keys set — planned."""
    import review as rv
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)

    cfg = {"enabled": True, "min_track": "S", "provider": "anthropic"}
    meta = {"track": "S", "review": {}}
    assert rv._should_run_external(no_external=False, reviewers_cfg=cfg,
                                   meta=meta) is True
    run, reason = review_plan.external_gate(no_external=False, ext_cfg=cfg,
                                            meta=meta)
    assert run is True
    assert reason is None


def test_should_run_external_anthropic_route_skips_with_reason_when_claude_cli_absent(
        tmp_path, monkeypatch):
    """AC-10 negative / fail-closed twin: no `claude` on PATH, no API keys
    set — skipped with the stated reason."""
    import review as rv
    _clear_keys(monkeypatch)
    _empty_path(tmp_path, monkeypatch)

    cfg = {"enabled": True, "min_track": "S", "provider": "anthropic"}
    meta = {"track": "S", "review": {}}
    assert rv._should_run_external(no_external=False, reviewers_cfg=cfg,
                                   meta=meta) is False
    run, reason = review_plan.external_gate(no_external=False, ext_cfg=cfg,
                                            meta=meta)
    assert run is False
    assert reason == "claude CLI not on PATH"


def test_should_run_external_key_gate_still_applies_to_openai_provider(
        tmp_path, monkeypatch):
    """Regression pin (impl-plan D-017): a resolved provider of `openai`
    with no key set is still skipped by the key check — the provider-aware
    change never widens or narrows the openai/google branch. This already
    held under the OLD unconditional-key-check code too."""
    import review as rv
    _clear_keys(monkeypatch)
    _stub_claude_on_path(tmp_path, monkeypatch)   # irrelevant to this branch

    cfg = {"enabled": True, "min_track": "S", "provider": "openai",
          "api_key_env": "OPENAI_API_KEY"}
    meta = {"track": "S", "review": {}}
    assert rv._should_run_external(no_external=False, reviewers_cfg=cfg,
                                   meta=meta) is False
    run, reason = review_plan.external_gate(no_external=False, ext_cfg=cfg,
                                            meta=meta)
    assert run is False
    assert reason == "$OPENAI_API_KEY not set"


def test_external_route_degrades_to_planned_with_note_when_models_yml_unreadable(
        monkeypatch):
    """C-004/C-007: an unreadable models.yml plans the external pass anyway
    (provider "unknown"), with a note — fail toward running, never toward
    silently dropping the pass."""
    import models as models_mod

    def _boom(force: bool = False):
        raise RuntimeError("simulated unreadable models.yml")

    monkeypatch.setattr(models_mod, "load_models", _boom)
    ext_cfg = {"model_ref": "review-external"}
    route = review_plan.external_route(ext_cfg, "M")
    assert route["provider"] == "unknown"
    assert route["note"] is not None


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
