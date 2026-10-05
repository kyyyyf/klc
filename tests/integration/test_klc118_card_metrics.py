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
import budget_guard  # noqa: E402
import token_journal  # noqa: E402


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

def test_card_render_records_no_attempt_and_leaves_a_provider_entry_untouched(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import artefacts

    mp = _seed(tmp_path, "KLC-MET1", phase="review:ack", track="M")
    meta = json.loads(mp.read_text())
    # KLC-119: pre-KLC-119 single-record shape — the writer's only reader
    # (normalize_attempts) accepts it as a one-attempt legacy list (AC-14).
    meta["metrics"] = {"tokens": {
        "review": {"in": 500, "out": 100, "cache_hit": 50, "source": "provider"},
    }}
    mp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    before = json.loads(mp.read_text())["metrics"]["tokens"]["review"]

    # KLC-119 AC-4: a render outside an open transaction must not touch
    # meta.json at all — it lands in the journal instead. render_card()
    # itself opens no transaction, so these calls simulate being inside one
    # (as every real call site is, directly or via the next state_tx's
    # drain), matching how `next.py` calls render_card from inside its own
    # state_tx.
    with token_journal.scope("KLC-MET1"):
        # (1) rendering a DIFFERENT phase must never touch the provider record.
        render = artefacts.render_card("KLC-MET1", "design", meta)
        after = json.loads(mp.read_text())["metrics"]["tokens"]
        assert after["review"] == before, \
            "a provider-sourced record for a different phase must be untouched"
        assert "design" not in after, "KLC-174: a render records no attempt"
        assert render.card_bytes > 0

        # (2) rendering the SAME phase (review) must not rewrite the existing
        # provider attempt, and (KLC-174) appends nothing next to it.
        artefacts.render_card("KLC-MET1", "review", meta)
    after2 = json.loads(mp.read_text())["metrics"]["tokens"]["review"]
    assert after2 == before, \
        "re-rendering review must leave its provider-sourced record verbatim"
    normalized = budget_guard.normalize_attempts(after2)
    sources = [a["source"] for a in normalized["attempts"]]
    assert sources == ["provider"], sources
    provider_attempt = normalized["attempts"][0]
    assert provider_attempt["in"] == 500 and provider_attempt["out"] == 100 \
        and provider_attempt["cache_hit"] == 50


def test_write_token_metrics_never_downgrades_provider_and_carries_card_bytes(
        tmp_path, monkeypatch):
    """Narrower unit-level check directly against budget_guard, mirroring the
    module's existing test style in tests/test_budget_guard.py."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    ticket = "KLC-MET2"
    mp = _seed(tmp_path, ticket, phase="review:ack", track="M")
    # KLC-119 AC-4: write_token_metrics is transaction-aware; simulate being
    # inside one (as `state_tx`/`_drain_journal` are in production) so this
    # unit-level check exercises the attempts-list semantics directly rather
    # than the journal-buffering path (covered by test_klc119_transaction_safety.py).
    with token_journal.scope(ticket):
        budget_guard.write_token_metrics(ticket, "review", 500, 100, 50,
                                         source="provider", card_bytes=1234)
        before = json.loads(mp.read_text())["metrics"]["tokens"]["review"]
        before_attempts = budget_guard.normalize_attempts(before)["attempts"]
        assert before_attempts[-1]["card_bytes"] == 1234

        # an estimated write must not rewrite the provider attempt (KLC-119
        # AC-3: appending cannot overwrite) ...
        budget_guard.write_token_metrics(ticket, "review", 10, 0, 0,
                                         source="estimated", card_bytes=999)
        after = json.loads(mp.read_text())["metrics"]["tokens"]["review"]
        attempts = budget_guard.normalize_attempts(after)["attempts"]
        assert attempts[0]["source"] == "provider"
        assert attempts[0]["in"] == 500 and attempts[0]["out"] == 100
        assert attempts[-1]["source"] == "estimated"
        # ...but a provider write for a phase with NO prior record just
        # records normally, and card_bytes is stored alongside token counts.
        budget_guard.write_token_metrics(ticket, "design", 20, 5, 0,
                                         source="estimated", card_bytes=321)
        design = json.loads(mp.read_text())["metrics"]["tokens"]["design"]
        design_attempts = budget_guard.normalize_attempts(design)["attempts"]
        assert design_attempts[-1]["source"] == "estimated"
        assert design_attempts[-1]["card_bytes"] == 321


# --- AC-6: klc next prints both numbers -------------------------------------- #

def test_klc_next_prints_card_bytes_human_and_json(
        tmp_path):
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("KLC_CARD_ROOT", None)
    _seed(tmp_path, "KLC-MET3", phase="discovery:ack", track="M")

    r = subprocess.run([sys.executable, str(KLC), "next", "KLC-MET3"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "bytes" in out

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
    assert "card" in info and "card_bytes" in info and "card_est_tokens" not in info
    card2 = Path(info["card"])
    assert card2.exists(), \
        "klc next --json must actually render the card, not skip it"
    assert info["card_bytes"] == card2.stat().st_size


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
