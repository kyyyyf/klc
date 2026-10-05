"""KLC-179 step-3 (AC-6): config/phases.yml is a prompt table, nothing more.

The transition walker (tracks, gotos, supersede lists, conditions) moved into
`core/skills/rules.py`. What stays in the file is what the rule table cannot know:
the prompt, the inputs, the outputs and the pick labels of each phase.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phases  # noqa: E402
import rules  # noqa: E402
from core.shared.yaml import parse as yaml_parse  # noqa: E402

KEPT = ["intake", "discovery-lite", "discovery", "acceptance-test-plan", "design", "build",
        "review", "manual", "integrate", "observe", "learn"]
RETIRED = ("xs-build", "review-lite", "detailed-test-plan")
FORBIDDEN_KEYS = {"tracks", "goto", "supersede", "condition", "auto_to_ack", "auto_ack_after",
                  "gate", "pick_records_to"}


def _walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _raw() -> dict:
    return yaml_parse((_FW / "config" / "phases.yml").read_text(encoding="utf-8"))


def test_phases_yml_is_prompt_table_only():
    raw = _raw()
    assert not FORBIDDEN_KEYS & set(_walk(raw)), FORBIDDEN_KEYS & set(_walk(raw))
    ids = [p["id"] for p in raw["phases"]]
    assert ids == KEPT
    for retired in RETIRED:
        assert retired not in ids
    assert len((_FW / "config" / "phases.yml").read_text(encoding="utf-8").splitlines()) < 150


def test_loader_has_no_walker_and_every_rule_phase_exists():
    model = phases.load_phases(force=True)
    for gone in ("next_phase", "prev_phase"):
        assert not hasattr(model, gone), gone
    for _fact, _applies, _action, light_phase, full_phase in rules.RULES:
        model.by_id(light_phase)
        model.by_id(full_phase)
    with_prompt = [p.id for p in model.ordered if p.prompt]
    assert "xs-build" not in with_prompt and "review-lite" not in with_prompt


def test_pick_kinds_decide_the_gate():
    model = phases.load_phases(force=True)
    gates = {(p.id, pk.label): pk.gate for p in model.ordered for pk in p.picks}
    # a human decision only on the spec and design approvals ...
    assert gates[("discovery-lite", "approve")] == "decision"
    assert gates[("discovery", "approve")] == "decision"
    assert gates[("design", "option-A-minimal")] == "decision"
    # ... every other forward pick is conditional ...
    for key in (("intake", "confirm-route"), ("acceptance-test-plan", "approve"),
                ("build", "approve"), ("review", "approve"),
                ("integrate", "merged"), ("observe", "clean"), ("learn", "archive")):
        assert gates[key] == "conditional", key
    # ... and a rework or route pick is always a decision.
    for key in (("review", "request-changes"), ("manual", "failed"), ("observe", "regression"),
                ("design", "revise-impl-plan"), ("discovery-lite", "upgrade-to-full")):
        assert gates[key] == "decision", key


def test_phase_roles_and_agents_follow_the_remaining_phases():
    import yaml
    roles = yaml.safe_load((_FW / "config" / "models.yml").read_text(encoding="utf-8"))
    for retired in RETIRED:
        assert retired not in roles["phase_roles"]
        assert retired not in (roles.get("per_track") or {}).get("XS", {})
    model = phases.load_phases(force=True)
    for p in model.ordered:
        if p.prompt:
            assert p.id in roles["phase_roles"], p.id
            assert (_FW / p.prompt).exists()
    for retired_agent in ("xs-fasttrack.md", "review-lite.md"):
        assert not (_FW / "core" / "agents" / retired_agent).exists()
        assert not (_FW / "klc-plugin" / "agents" / retired_agent).exists()
