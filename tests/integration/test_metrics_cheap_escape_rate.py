#!/usr/bin/env python3
"""Test that metrics rollup computes cheap_escape_rate per track.

cheap_escape_rate = (cheap/lite reviews that had regression/rework) / (all cheap/lite reviews)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))


def _make_ticket(tickets_dir: Path, key: str, track: str, *,
                 review_depth: str = "full",
                 regression: int = 0,
                 rework: dict | None = None) -> None:
    tdir = tickets_dir / key
    tdir.mkdir(parents=True)
    meta = {
        "ticket": key,
        "kind": "tech",
        "kind_source": "user",
        "phase": "archived",
        "phase_history": [
            {"phase": "intake:work", "started_at": "2026-06-01T00:00:00Z",
             "finished_at": "2026-06-01T00:01:00Z"},
            {"phase": "learn:work", "started_at": "2026-06-02T00:00:00Z",
             "finished_at": "2026-06-02T01:00:00Z"},
        ],
        "track": track,
        "estimate": {"total": 5},
        "rework_count": rework or {},
        "regression_observed": regression,
        "metrics": {
            "review_depth": review_depth,
        },
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def test_cheap_escape_rate_in_rollup() -> None:
    """Rollup emits cheap_escape_rate per track from fixture tickets."""
    import metrics as m_mod
    import argparse

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        tickets_dir = tmp / ".klc" / "tickets"
        tickets_dir.mkdir(parents=True)
        knowledge_dir = tmp / ".klc" / "knowledge"
        knowledge_dir.mkdir(parents=True)

        # S-track: 2 cheap reviews, 1 with rework → rate = 0.5
        _make_ticket(tickets_dir, "S-001", "S", review_depth="cheap", rework={"build": 1})
        _make_ticket(tickets_dir, "S-002", "S", review_depth="cheap", rework={})
        # M-track: 1 lite review with regression → rate = 1.0
        _make_ticket(tickets_dir, "M-001", "M", review_depth="lite", regression=1)
        # M-track: 1 full review → does not count
        _make_ticket(tickets_dir, "M-002", "M", review_depth="full")

        os.environ["PROJECT_ROOT"] = tmp_str
        try:
            args = argparse.Namespace(output=None)
            m_mod.cmd_rollup(args)
        finally:
            os.environ.pop("PROJECT_ROOT", None)

        out_path = knowledge_dir / "process-metrics.json"
        assert out_path.exists(), "process-metrics.json not written"
        data = json.loads(out_path.read_text())
        per_track = data.get("per_track", {})

        assert "cheap_escape_rate" in per_track.get("S", {}), (
            f"expected cheap_escape_rate in S track, got: {per_track.get('S', {}).keys()}"
        )
        assert "cheap_escape_rate" in per_track.get("M", {}), (
            f"expected cheap_escape_rate in M track, got: {per_track.get('M', {}).keys()}"
        )

        s_rate = per_track["S"]["cheap_escape_rate"]
        m_rate = per_track["M"]["cheap_escape_rate"]

        assert abs(s_rate - 0.5) < 0.01, f"S cheap_escape_rate expected 0.5, got {s_rate}"
        assert abs(m_rate - 1.0) < 0.01, f"M cheap_escape_rate expected 1.0, got {m_rate}"
        print(f"PASS: S cheap_escape_rate={s_rate:.2f}, M cheap_escape_rate={m_rate:.2f}")


if __name__ == "__main__":
    test_cheap_escape_rate_in_rollup()
    print("ALL METRICS TESTS PASSED")
