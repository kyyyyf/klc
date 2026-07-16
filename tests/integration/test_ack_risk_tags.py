#!/usr/bin/env python3
"""tests/integration/test_ack_risk_tags.py — KLC-062 AC-3 regression guard.

KLC-062 makes `klc remind` read-only by adding a `persist=False` flag to the
completion probe. This test pins the OTHER half of the contract: the persisting
(ack) path — where `persist` defaults to True — must STILL sync `risk_tags` from
spec.md into meta.json when a real `discovery` completion is acked. In other
words, making remind side-effect-free must not regress risk-tag persistence at
the genuine phase transition.

`klc ack` calls `phase_completion.can_complete(ticket, phase)` (persist defaulting
True) as its manual-completion detector before any holder/transaction machinery,
so driving the real verb exercises the exact write path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
KLC = FW_ROOT / "scripts" / "klc"

ID = "acker@example.com"


def _git_init(path: Path, email: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", email], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Acker"], cwd=path, check=True)


def _fabricate_completable_discovery(root: Path, ticket: str) -> Path:
    """Completable `discovery:work` ticket held by ID; returns meta.json path."""
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "bug", "phase": "discovery:work",
        "phase_history": [], "track": "M", "route_hint": "M",
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1,
                     "manual": 1, "total": 5},
        "layer": "code", "affected_modules": ["core/skills"],
        "created": "2026-01-01T00:00:00Z",
        "holder": {"id": ID, "machine": "m", "since": "2026-01-01T00:00:00Z"},
    }
    (tdir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (tdir / "spec.md").write_text(
        "---\n"
        f"ticket: {ticket}\n"
        "kind: bug\n"
        "authority: human\n"
        "risk_tags: [data]\n"
        "---\n\n"
        f"# {ticket} — ack risk_tags fixture\n\n"
        "## Goals\n\nDo the thing.\n\n"
        "## Acceptance Criteria\n\n1. AC-1: given X, when Y, then Z.\n\n"
        "## Approaches considered\n\n"
        "- Approach A — one way to do it.\n"
        "- Approach B — another way to do it.\n\n"
        "Picked: Approach A — because reasons.\n\n"
        "## Estimate\n\n"
        "- complexity: 2\n- uncertainty: 1\n- risk: 1\n- manual: 1\n"
        "- total: 5\n- track: M\n",
        encoding="utf-8",
    )
    return tdir / "meta.json"


def test_ack_discovery_persists_risk_tags() -> None:
    """AC-3: a real `klc ack` of a completable discovery ticket still writes
    risk_tags from spec.md into meta.json (persist defaults True)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _git_init(root, ID)
        meta_p = _fabricate_completable_discovery(root, "KLC-907")

        # Sanity: risk_tags absent before the ack.
        assert "risk_tags" not in json.loads(meta_p.read_text(encoding="utf-8"))

        env = {**os.environ, "PROJECT_ROOT": str(root)}
        env.pop("KLC_TICKETS_DIR", None)
        subprocess.run(
            [sys.executable, str(KLC), "ack", "KLC-907", "--pick", "1"],
            capture_output=True, text=True, env=env, cwd=str(root),
        )

        meta_after = json.loads(meta_p.read_text(encoding="utf-8"))
        assert meta_after.get("risk_tags") == ["data"], (
            "ack did not persist risk_tags from spec.md — AC-3 regression; "
            f"meta.risk_tags={meta_after.get('risk_tags')!r}"
        )
