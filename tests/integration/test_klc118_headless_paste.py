#!/usr/bin/env python3
"""KLC-118 step-4 — AC-4: the headless dispatch path keeps the role prompt
inside the prompt text.

Per impl-plan-review finding F-3, this drives the prompt through
`autorunner._dispatch` -> `_card_path` -> `resolve_phase(executor=
EXECUTOR_HEADLESS)` (the actual step-4 wiring), NOT an independently
constructed paste-mode card — a caller mistakenly wired to dispatch mode
must make this test fail.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (_FW_ROOT, _FW_ROOT / "core" / "skills", _FW_ROOT / "core" / "phases"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_CLEAN_SIG = {
    "advisory": "", "scope_expansion": False, "sentinels": False,
    "mutation": False, "budget_overrun": False, "verdict": "APPROVED",
    "route_confidence": "high",
}

_SPEC = (
    "---\nticket: {t}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
    "## Goals\nDo thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
    "## Affected\nm: core/x.py, src=core/x.py:1\n"
    "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
)


def _flush_phases_cache():
    import core.skills.phases as ph_mod
    ph_mod._CACHE = None
    import phases as ph_mod2
    ph_mod2._CACHE = None


def _modules_json(tmp_path: Path):
    idx = tmp_path / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(
        json.dumps({"modules": [{"name": "m", "src": ["core/x.py"], "tests": [],
                                 "phase": "stable"}]}), encoding="utf-8")


def _make_ticket(tmp_path: Path, ticket: str, phase: str, track: str) -> Path:
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": phase, "track": track,
        "route_confidence": "high", "affected_modules": ["m"], "layer": "code",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0,
                     "total": 3},
        "budgets": {"mutation_fix_attempts": 0}, "risk_tags": [],
        "phase_history": [],
    }
    (td / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (td / "spec.md").write_text(_SPEC.format(t=ticket), encoding="utf-8")
    _modules_json(tmp_path)
    return td


def test_headless_dispatch_prompt_contains_role_prompt_verbatim(tmp_path,
                                                                 monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _flush_phases_cache()
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals",
                        lambda t, p: dict(_CLEAN_SIG))

    _make_ticket(tmp_path, "KLC-HP1", "review:work", "S")

    # Spy on phase_resolver.resolve_phase itself (not a re-implementation of
    # the wiring) — proves the prompt actually travelled through
    # autorunner._dispatch -> _card_path -> resolve_phase(executor=
    # EXECUTOR_HEADLESS), per impl-plan-review F-3, rather than an
    # independently-constructed paste-mode card that would pass even if
    # autorunner never asked phase_resolver anything.
    import phase_resolver as pr
    resolve_calls: list = []
    _orig_resolve = pr.resolve_phase

    def _spy(ticket, phase_id, **kw):
        resolve_calls.append((ticket, phase_id, kw.get("executor")))
        return _orig_resolve(ticket, phase_id, **kw)

    monkeypatch.setattr(pr, "resolve_phase", _spy)

    import autorunner
    calls: list = []

    def fake_dispatch(phase_id, prompt_path, out_path, *, track=None,
                      ticket=None, **kw):
        calls.append({"phase": phase_id, "prompt": str(prompt_path)})
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("# response\n\nGreen.\n", encoding="utf-8")
        for rel in (__import__("phases").load_phases().by_id(phase_id).outputs or []):
            p = tmp_path / ".klc" / "tickets" / "KLC-HP1" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {rel}\n\ncontent\n", encoding="utf-8")
        return 0

    autorunner.run("KLC-HP1", dispatch=fake_dispatch, cap=20)

    review_resolves = [c for c in resolve_calls if c[1] == "review"]
    assert review_resolves, (
        "autorunner never asked phase_resolver.resolve_phase for the review "
        "phase — the prompt did not travel through the resolver-driven wiring")
    assert review_resolves[-1][2] == pr.EXECUTOR_HEADLESS, (
        f"autorunner must resolve the headless dispatch with "
        f"executor=EXECUTOR_HEADLESS, got {review_resolves[-1]!r}")

    review_call = next(c for c in calls if c["phase"] == "review")
    card_text = Path(review_call["prompt"]).read_text(encoding="utf-8")

    role_prompt = (_FW_ROOT / "core" / "agents" / "review.md").read_text(
        encoding="utf-8")
    assert role_prompt in card_text, \
        "headless dispatch must carry the full role prompt verbatim"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
