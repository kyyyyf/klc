"""KLC-114 step-7: `_run_reviewer` dispatches `core/agents/review/per-step.md`
as the role prompt, with the composed review package as a labelled input,
under an explicit `per-step-review` role — instead of sending the review
input as the role prompt under the unnamed default (AC-9)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_run_reviewer_sends_per_step_prompt_and_review_package_as_labelled_input(tmp_path, monkeypatch):
    """AC-9: the dispatch call records `core/agents/review/per-step.md` as
    `prompt_path`, and the composed review package as a labelled input —
    never the review input itself as the role prompt."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-RD01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    build = ticket_dir / "build"
    build.mkdir(parents=True)
    (ticket_dir / "meta.json").write_text(
        json.dumps({"ticket": ticket, "track": "M"}), encoding="utf-8")
    (build / "step-1-brief.md").write_text("brief\n", encoding="utf-8")
    (build / "step-1-impl-report.md").write_text("report\n", encoding="utf-8")

    import build_orchestrator as bo

    calls = []

    def fake_dispatch(role, prompt_path, out_path, *, inputs=None, track=None):
        calls.append((role, prompt_path, inputs, track))
        return 0

    bo._run_reviewer(ticket, 1, fake_dispatch)

    assert len(calls) == 1
    role, prompt_path, inputs, track = calls[0]
    assert role == "per-step-review"
    assert Path(prompt_path).name == "per-step.md"
    assert "core/agents/review" in str(prompt_path).replace("\\", "/")
    assert inputs is not None and any("step package" in k for k in inputs)
    assert track == "M"


def test_per_step_review_role_no_longer_resolves_to_defaults():
    """AC-9: `load_models().resolve("per-step-review", track="M")` no longer
    silently inherits the unnamed default — it resolves through a named
    `phase_roles` mapping."""
    from models import load_models
    resolved = load_models().resolve("per-step-review", track="M")
    assert resolved.source != "default", resolved
