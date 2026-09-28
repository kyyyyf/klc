#!/usr/bin/env python3
"""KLC-120 step-2 — AC-8: config/reviewers.yml's `external_reviewer` block
resolves its provider and model through config/models.yml's
`review-external` pseudo-phase instead of a hard-coded openai/gpt-4o pair,
while `min_track: S` stays unchanged (D-002).

Expected model IDs are read from the shipped config/models.yml itself
(spec's 2026-09-28 operator note on AC-8) — never hard-coded, because
KLC-130 already refreshed those IDs once.
"""
from __future__ import annotations

import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import models as models_mod  # noqa: E402
import review_plan  # noqa: E402
from _yaml import parse as _yml_parse  # noqa: E402


def _real_external_cfg() -> dict:
    cfg = _yml_parse((FW_ROOT / "config" / "reviewers.yml").read_text(encoding="utf-8"))
    return cfg["external_reviewer"]


def test_external_reviewer_resolves_to_claude_sonnet_on_s_and_m(monkeypatch):
    """AC-8: on S and M, the external reviewer resolves to whatever
    models.yml's `external` role currently names."""
    monkeypatch.setenv("PROJECT_ROOT", str(FW_ROOT))
    models_mod._reset_cache()
    expected = models_mod.load_models().roles["external"]
    ext_cfg = _real_external_cfg()
    for track in ("S", "M"):
        route = review_plan.external_route(ext_cfg, track)
        assert route["provider"] == expected.provider
        assert route["model"] == expected.model
    models_mod._reset_cache()


def test_external_reviewer_resolves_to_claude_opus_on_l(monkeypatch):
    """AC-8: L upgrades through models.yml's own `per_track.L.review-external`
    override — read the override's target role, never a hard-coded model."""
    monkeypatch.setenv("PROJECT_ROOT", str(FW_ROOT))
    models_mod._reset_cache()
    m = models_mod.load_models()
    role_name = m.per_track["L"]["review-external"]
    expected = m.roles[role_name]
    ext_cfg = _real_external_cfg()
    route = review_plan.external_route(ext_cfg, "L")
    assert route["provider"] == expected.provider
    assert route["model"] == expected.model
    models_mod._reset_cache()


def test_external_reviewer_min_track_still_s():
    """Regression twin: the provider/model rewrite leaves `min_track: S`
    unchanged (D-002)."""
    assert _real_external_cfg().get("min_track") == "S"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
