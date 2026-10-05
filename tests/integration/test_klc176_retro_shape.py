"""KLC-176 step-5 (AC-9): the retrospective is at most 40 lines with three fixed
headings; a longer or headless file surfaces an advisory at the learn ack and
never blocks it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import advisories  # noqa: E402
from core.skills import phase_completion  # noqa: E402

GOOD = (
    "# Retrospective\n\n## What the gates missed\n- nothing\n\n"
    "## Token cost by phase\nn/a\n\n## One process change\n- none\n"
)


def _seed(tmp_path: Path, monkeypatch, body: str) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc/tickets/KLC-930"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "meta.json").write_text(json.dumps({
        "ticket": "KLC-930", "kind": "tech", "phase": "learn:work", "track": "M",
        "phase_history": [{"phase": "learn", "started_at": "2026-10-01T00:00:00Z"}],
    }), encoding="utf-8")
    (tdir / "retrospective.md").write_text(body, encoding="utf-8")
    return tdir


def test_well_shaped_retro_has_no_advisory(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, GOOD)
    assert phase_completion.retro_shape_advisories("KLC-930") == []


def test_long_or_headless_retro_surfaces_advisory(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, GOOD + "filler\n" * 40)
    msgs = [r["message"] for r in phase_completion.retro_shape_advisories("KLC-930")]
    assert any("longer than 40 lines" in m for m in msgs)

    _seed(tmp_path, monkeypatch, "# Retrospective\n\n## What happened\n- x\n")
    recs = phase_completion.retro_shape_advisories("KLC-930")
    assert {r["source"] for r in recs} == {"retro-shape"}
    msgs = " ".join(r["message"] for r in recs)
    for h in ("What the gates missed", "Token cost by phase", "One process change"):
        assert h in msgs


def test_learn_ack_surfaces_the_advisory_without_blocking(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, "# Retrospective\n\nlong story\n")
    ok, summary = phase_completion.can_complete("KLC-930", "learn")
    assert ok is True
    assert summary
    env = advisories.read("KLC-930", "learn")
    assert any(r["source"] == "retro-shape" for r in env["records"])
