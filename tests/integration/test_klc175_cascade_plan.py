"""KLC-175 step-3 (AC-3, AC-4, AC-5): the review plan is three layers.

Layer 0 (deterministic checks) is never a pass. Layer 1 is exactly one
`code-review`. Layer 2 holds only the specialists whose signal is in the diff.
The external reviewer is default-on for track L only; S/M opt in through
`reviewers.yml`. The in-client (`--plan-only`) and headless paths plan the same
reviewers.

`decide` is driven for real; only the three subprocess-backed inputs are
replaced by stand-ins that return their REAL shapes (a sentinel count, a
path -> tier map, scope_delta's report dict)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import models as models_mod  # noqa: E402
import review as rv  # noqa: E402
import review_cascade as rc  # noqa: E402
import review_plan  # noqa: E402
import review_signals  # noqa: E402
from test_klc120_review_plan import (  # noqa: E402
    _HARMLESS_DIFF, _seed_project, _stub_claude_on_path, _write_diff,
)

SPECIALISTS = {"security", "architecture", "performance", "deep-impact"}
_NO_DRIFT = {"planned": [], "actual": [], "drift": [], "expansion": [],
             "shared_touched": [], "unknown_files": []}


def _diff(path: str, added: str) -> str:
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1 +1 @@\n-old\n+{added}\n")


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc" / "tickets" / "KLC-T3"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"ticket": "KLC-T3", "track": "S"}),
                                 encoding="utf-8")
    return tmp_path


def _decide(root, diff_text, *, hits=0, tiers=None, track="S", cfg=None):
    diff = root / "d.patch"
    diff.write_text(diff_text, encoding="utf-8")
    meta = root / ".klc" / "tickets" / "KLC-T3" / "meta.json"
    meta.write_text(json.dumps({"ticket": "KLC-T3", "track": track}), encoding="utf-8")
    tiers = tiers if tiers is not None else {"docs/readme.md": "peripheral"}
    with patch.object(rc, "_get_sentinel_hits", return_value=hits), \
         patch.object(rc, "_get_file_tiers", return_value=tiers), \
         patch.object(rc, "_load_cascade_config",
                      return_value={"enabled": True, **(cfg or {})}), \
         patch("scope_delta.compare", return_value=_NO_DRIFT):
        return rc.decide("KLC-T3", diff)


@pytest.mark.parametrize("track", ["S", "M", "L"])
def test_no_signal_plan_is_one_code_review(root, track):
    d = _decide(root, _diff("docs/readme.md", "docs update"), track=track)
    assert d.layers["layer1"] == "code-review"
    assert d.layers["layer2"] == []
    assert "layer0" in d.layers and "code-review" not in d.layers["layer0"]
    assert d.as_dict()["layers"] == d.layers


@pytest.mark.parametrize("track", ["S", "M", "L"])
def test_no_signal_plan_document_plans_one_code_review_and_no_specialist(
        tmp_path, monkeypatch, track):
    project_root, spec = _seed_project(tmp_path, track=track)
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)
    planned_by_path = {}
    for label, extra in (("client", ["--plan-only"]), ("headless", [])):
        assert rv.main(["--diff", str(diff), "--spec", str(spec), *extra]) == 0
        plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990" / "review"
                           / "review-plan-r1.json").read_text(encoding="utf-8"))
        assert plan["path"] == label
        planned = [p["reviewer"] for p in plan["passes"]
                   if p["status"] in ("planned", "executed")
                   and p["reviewer"] not in ("drift", "external")]
        assert planned == ["code-review"], planned
        names = [p["reviewer"] for p in plan["passes"]]
        assert "test-coverage" not in names
        assert not any(n.startswith("layer0") for n in names)   # layer 0 is no pass
        assert SPECIALISTS <= set(names)                        # listed, skipped
        planned_by_path[label] = planned
    assert planned_by_path["client"] == planned_by_path["headless"]


@pytest.mark.parametrize("diff_text,kw,expected", [
    (_diff("docs/readme.md", "docs update"), {"hits": 1}, ["security"]),
    (_diff("docs/readme.md", "docs update"),
     {"tiers": {"auth/login.py": "critical"}}, ["security"]),
    (_diff("src/a.py", "def helper():"), {}, ["architecture", "deep-impact"]),
    (_diff("src/a.py", "x = 1  # perf:hot"), {}, ["performance"]),
    (_diff("conf/app.yaml", "key: 1"), {}, ["deep-impact"]),
    (_diff("docs/readme.md", "docs update"), {}, []),
])
def test_each_signal_adds_only_its_specialist(root, diff_text, kw, expected):
    d = _decide(root, diff_text, **kw)
    assert d.layers["layer2"] == expected
    assert d.layers["layer1"] == "code-review"


def test_dependency_edge_adds_architecture_only_with_a_known_module(root):
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True)
    (idx / "modules.json").write_text(json.dumps({"modules": [{"name": "billing"}]}),
                                      encoding="utf-8")
    with_edge = _decide(root, _diff("src/a.py", "from billing import invoice"))
    assert "architecture" in with_edge.layers["layer2"]
    without = _decide(root, _diff("src/a.py", "from elsewhere import invoice"))
    assert "architecture" not in without.layers["layer2"]


def test_hot_path_glob_from_reviewers_yml_marks_performance_only(root):
    cfg = {"specialists": {"performance": {"hot_path_globs": ["src/hot/*.py"]}}}
    hot = _decide(root, _diff("src/hot/loop.py", "x = 1"), cfg=cfg)
    assert hot.layers["layer2"] == ["performance"]
    cold = _decide(root, _diff("src/cold/loop.py", "x = 1"), cfg=cfg)
    assert cold.layers["layer2"] == []
    assert review_signals.signals(_diff("src/hot/loop.py", "x = 1"), None, {},
                                  {})["hot_path"] is False   # default: no globs


def test_specialists_for_maps_each_signal_to_its_specialist_only():
    assert rc.specialists_for({}) == []
    assert rc.specialists_for({"sentinel_hit": True}) == ["security"]
    assert rc.specialists_for({"critical_tier": True}) == ["security"]
    assert rc.specialists_for({"changed_public_api": True}) == ["architecture"]
    assert rc.specialists_for({"dependency_edge_added": True}) == ["architecture"]
    assert rc.specialists_for({"hot_path": True}) == ["performance"]
    assert rc.specialists_for({"deep_impact": True}) == ["deep-impact"]


# --- AC-5 ------------------------------------------------------------------

def _ext_cfg():
    cfg, _note = review_plan.load_reviewers_cfg()
    return dict(cfg["external_reviewer"])


def test_external_default_on_only_for_l(monkeypatch):
    monkeypatch.setattr(review_plan.shutil, "which", lambda *_a, **_k: "/bin/claude")
    cfg = _ext_cfg()
    assert cfg["default_on_tracks"] == ["L"]
    route = {"provider": "anthropic"}
    got = {t: review_plan.external_gate(no_external=False, ext_cfg=cfg,
                                        meta={"track": t}, route=route)
           for t in ("XS", "S", "M", "L")}
    assert got["L"] == (True, None)
    for t in ("XS", "S", "M"):
        assert got[t][0] is False, t
    assert "default_on_tracks" in got["S"][1] and "opt_in_tracks" in got["S"][1]
    # --no-external still wins on L
    assert review_plan.external_gate(no_external=True, ext_cfg=cfg,
                                     meta={"track": "L"}, route=route)[0] is False


def test_external_on_s_and_m_only_when_reviewers_yml_opts_in(monkeypatch):
    monkeypatch.setattr(review_plan.shutil, "which", lambda *_a, **_k: "/bin/claude")
    cfg = {**_ext_cfg(), "opt_in_tracks": ["M"]}
    route = {"provider": "anthropic"}
    run = lambda t: review_plan.external_gate(  # noqa: E731
        no_external=False, ext_cfg=cfg, meta={"track": t}, route=route)[0]
    assert run("M") is True and run("L") is True
    assert run("S") is False


@pytest.mark.parametrize("track,external_planned", [("S", False), ("M", False), ("L", True)])
def test_plan_document_external_follows_track(tmp_path, monkeypatch, track, external_planned):
    project_root, spec = _seed_project(tmp_path, track=track)
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    diff = _write_diff(tmp_path, "diff.patch", _HARMLESS_DIFF)
    assert rv.main(["--diff", str(diff), "--spec", str(spec), "--plan-only"]) == 0
    plan = json.loads((project_root / ".klc" / "tickets" / "KLC-990" / "review"
                       / "review-plan-r1.json").read_text(encoding="utf-8"))
    ext = next(p for p in plan["passes"] if p["reviewer"] == "external")
    assert (ext["status"] == "planned") is external_planned, ext


def test_classifier_reads_the_real_tiers_yml_and_flags_an_auth_path_critical(tmp_path):
    """The critical-tier signal rests on classify_tier, which used to crash on
    the real config (the in-tree parser takes text, not a Path, and cannot read
    tiers.yml's folded scalars), so every diff came back tier-less."""
    import classify_tier
    cfg = classify_tier.load_tiers_config()
    assert "critical" in cfg["tiers"]
    diff = tmp_path / "t.patch"
    diff.write_text(_diff("core/auth/foo.py", "x = 1"), encoding="utf-8")
    tiers = rc._get_file_tiers(diff)
    assert tiers == {"core/auth/foo.py": "critical"}
