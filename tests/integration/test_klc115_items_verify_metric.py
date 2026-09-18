"""KLC-115 step-6: items_verify.cmd_stats reports the undecidable share as a
named ratio (AC-14).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import items_verify  # noqa: E402


def test_stats_reports_undecidable_share_as_named_ratio(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "verification-log.jsonl"
    records = (
        [{"verdict": "confirmed"}] * 3
        + [{"verdict": "needs-review"}] * 1
        + [{"verdict": "undecidable"}] * 6
    )
    log_path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    monkeypatch.setattr(items_verify, "klc_verification_log", lambda: log_path)

    rc = items_verify.cmd_stats(argparse.Namespace(last=0))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["runs"] == 10
    assert out["counts"]["undecidable"] == 6
    assert out["undecidable_share"] == 0.6
