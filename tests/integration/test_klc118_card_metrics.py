#!/usr/bin/env python3
"""KLC-118 step-5 — AC-5 / AC-6: every card render records its byte size and
estimated token count into `meta.json:metrics.tokens.<phase>` without ever
downgrading a `source: "provider"` record, and `klc next` prints both
numbers on entering a `:work` phase (human and `--json`).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"
SKILLS_DIR = FW_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS_DIR))


def _seed(tmp_path: Path, ticket: str, *, phase: str, track: str = "M",
          **extra) -> Path:
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
    mp = tdir / "meta.json"
    mp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "spec.md").write_text(
        "## Goals\nfake\n## Acceptance Criteria\n- AC-1\n", encoding="utf-8")
    (tdir / "test-plan.md").write_text("fake\n", encoding="utf-8")
    return mp


# --- AC-5: no-downgrade + carry-forward -------------------------------------- #

def test_card_render_records_estimated_tokens_without_downgrading_a_provider_entry(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import artefacts

    mp = _seed(tmp_path, "KLC-MET1", phase="review:ack", track="M")
    meta = json.loads(mp.read_text())
    meta["metrics"] = {"tokens": {
        "review": {"in": 500, "out": 100, "cache_hit": 50, "source": "provider"},
    }}
    mp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    before = json.loads(mp.read_text())["metrics"]["tokens"]["review"]

    # (1) rendering a DIFFERENT phase must never touch the provider record.
    render = artefacts.render_card("KLC-MET1", "design", meta)
    after = json.loads(mp.read_text())["metrics"]["tokens"]
    assert after["review"] == before, \
        "a provider-sourced record for a different phase must be untouched"
    assert after["design"]["source"] == "estimated"
    assert after["design"]["card_bytes"] == render.card_bytes
    assert render.est_tokens > 0

    # (2) rendering the SAME phase (review) must not downgrade it either.
    artefacts.render_card("KLC-MET1", "review", meta)
    after2 = json.loads(mp.read_text())["metrics"]["tokens"]["review"]
    assert after2 == before, \
        "re-rendering review must not downgrade its provider-sourced record"


def test_write_token_metrics_never_downgrades_provider_and_carries_card_bytes(
        tmp_path, monkeypatch):
    """Narrower unit-level check directly against budget_guard, mirroring the
    module's existing test style in tests/test_budget_guard.py."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import budget_guard

    ticket = "KLC-MET2"
    mp = _seed(tmp_path, ticket, phase="review:ack", track="M")
    budget_guard.write_token_metrics(ticket, "review", 500, 100, 50,
                                     source="provider", card_bytes=1234)
    before = json.loads(mp.read_text())["metrics"]["tokens"]["review"]
    assert before["card_bytes"] == 1234

    # an estimated write must not downgrade the provider source...
    budget_guard.write_token_metrics(ticket, "review", 10, 0, 0,
                                     source="estimated", card_bytes=999)
    after = json.loads(mp.read_text())["metrics"]["tokens"]["review"]
    assert after["source"] == "provider"
    assert after["in"] == 500 and after["out"] == 100
    # ...but a provider write for a phase with NO prior record just records
    # normally, and card_bytes is stored alongside the token counts.
    budget_guard.write_token_metrics(ticket, "design", 20, 5, 0,
                                     source="estimated", card_bytes=321)
    design = json.loads(mp.read_text())["metrics"]["tokens"]["design"]
    assert design["source"] == "estimated"
    assert design["card_bytes"] == 321


# --- AC-6: klc next prints both numbers -------------------------------------- #

def test_klc_next_prints_card_bytes_and_estimated_tokens_human_and_json(
        tmp_path):
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("KLC_CARD_ROOT", None)
    _seed(tmp_path, "KLC-MET3", phase="discovery:ack", track="M")

    r = subprocess.run([sys.executable, str(KLC), "next", "KLC-MET3"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "bytes" in out
    assert "est" in out.lower() or "token" in out.lower()

    import re
    m = re.search(r"cat (\S+)", out)
    assert m, out
    card_path = Path(m.group(1).rstrip("`"))
    assert card_path.exists()

    _seed(tmp_path, "KLC-MET4", phase="discovery:ack", track="M")
    r2 = subprocess.run(
        [sys.executable, str(KLC), "next", "KLC-MET4", "--json"],
        capture_output=True, text=True, env=env)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    info = json.loads(r2.stdout)
    assert "card" in info and "card_bytes" in info and "card_est_tokens" in info
    card2 = Path(info["card"])
    assert card2.exists(), \
        "klc next --json must actually render the card, not skip it"
    assert info["card_bytes"] == card2.stat().st_size

    sys.path.insert(0, str(SKILLS_DIR))
    import budget_guard
    assert info["card_est_tokens"] == budget_guard.estimate_tokens(
        card2.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
