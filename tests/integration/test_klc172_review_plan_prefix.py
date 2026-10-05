"""KLC-172 step-5 (AC-13): review.py writes a review plan for any ticket
prefix that matches config/ticket-id.yml, not only `KLC-`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import models as models_mod  # noqa: E402
import review as rv  # noqa: E402
import review_cascade  # noqa: E402
from test_klc120_review_plan import (  # noqa: E402
    _HARMLESS_DIFF, _make_decide, _stub_claude_on_path, _write_diff,
)


def _seed(tmp_path: Path, ticket: str) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    (root / ".klc" / "config").mkdir(parents=True)
    (root / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "tech", "kind_source": "user",
            "phase": "review:work", "phase_history": [], "track": "M",
            "route_hint": "M", "route_confidence": "high",
            "affected_modules": [], "estimate": None, "layer": "code",
            "jira_url": None, "created": "2026-01-01T00:00:00Z"}
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return root, tdir / "spec.md"


@pytest.mark.parametrize("ticket", ["KLC-990", "PROJ-123"])
def test_review_plan_written_for_non_klc_prefix(tmp_path, monkeypatch, ticket):
    root, spec = _seed(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    monkeypatch.setattr(review_cascade, "decide",
                        _make_decide(True, "core files touched", "core"))
    diff = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)
    assert rv.main(["--diff", str(diff), "--spec", str(spec), "--plan-only"]) == 0
    plan = root / ".klc" / "tickets" / ticket / "review" / "review-plan-r1.json"
    assert plan.is_file()
    assert json.loads(plan.read_text(encoding="utf-8"))["ticket"] == ticket
