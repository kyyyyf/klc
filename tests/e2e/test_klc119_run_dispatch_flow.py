#!/usr/bin/env python3
"""KLC-119 step-4 — AC-6/AC-10 end to end: drive one fixture ticket through
`klc next` -> `klc ack` -> `klc step`, recording three `estimated` attempts
across three distinct phases, then assert the rollup's `source_counts`
reflects them.
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


def _seed(tmp_path: Path, ticket: str, *, phase: str, track: str = "M") -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")
    (tdir / "spec.md").write_text(
        "## Goals\nfake\n## Acceptance Criteria\n- AC-1\n", encoding="utf-8")
    (tdir / "test-plan.md").write_text("fake\n", encoding="utf-8")
    return tdir


def _set_phase(tdir: Path, phase: str) -> None:
    meta = json.loads((tdir / "meta.json").read_text())
    meta["phase"] = phase
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")


def test_fixture_ticket_through_next_ack_step_writes_no_estimated_attempt_and_rollup_counts_the_three_provider_attempts(
        tmp_path):
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    env.pop("KLC_CARD_ROOT", None)
    ticket = "KLC-400"
    tdir = _seed(tmp_path, ticket, phase="discovery:ack", track="M")

    r1 = subprocess.run([sys.executable, str(KLC), "next", ticket],
                       capture_output=True, text=True, env=env)
    assert r1.returncode == 0, r1.stdout + r1.stderr  # -> acceptance-test-plan:work

    _set_phase(tdir, "acceptance-test-plan:ack-needed")
    r2 = subprocess.run(
        [sys.executable, str(KLC), "ack", ticket, "--pick", "1"],
        capture_output=True, text=True, env=env)
    assert r2.returncode == 0, r2.stdout + r2.stderr  # -> design:work

    r3 = subprocess.run([sys.executable, str(KLC), "step", ticket, "1"],
                       capture_output=True, text=True, env=env)
    assert r3.returncode == 0, r3.stdout + r3.stderr

    # KLC-174: nothing writes an `estimated` attempt any more, so the flow
    # alone leaves no attempt. REAL usage is what the rollup counts: seed one
    # provider attempt per phase the flow walked through, as a dispatch with
    # a usage block would.
    meta = json.loads((tdir / "meta.json").read_text())
    tokens = meta.setdefault("metrics", {}).setdefault("tokens", {})
    for n, phase in enumerate(("discovery", "acceptance-test-plan", "design")):
        tokens[phase] = {"attempts": [{
            "id": f"att-{n}", "source": "provider", "in": 100, "out": 10,
            "cache_hit": 0, "cost_usd": 0.01,
        }]}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")

    r4 = subprocess.run([sys.executable, str(KLC), "metrics", "--rollup"],
                       capture_output=True, text=True, env=env)
    assert r4.returncode == 0, r4.stdout + r4.stderr

    payload = json.loads(
        (tmp_path / ".klc" / "knowledge" / "process-metrics.json").read_text())
    m_track = payload["per_track"]["M"]
    counts = {
        src: sum(b["source_counts"][src]
                 for b in m_track["tokens_by_phase"].values())
        for src in ("provider", "estimated")
    }
    assert counts == {"provider": 3, "estimated": 0}, m_track["tokens_by_phase"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
