"""KLC-172 step-3: the impl role is sent once per step; the per-step reviewer gets the step diff."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

_KEY = "KLC-T9"

_PLAN = textwrap.dedent("""\
    ---
    ticket: KLC-T9
    kind: impl-plan
    ---

    ## step-1 — first step

    - **Goal:** do first thing
    - **Interfaces:** `def first() -> None`
    - **Expected:** first called
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T9 step-1: first step
    - **Affected:** src/first.py
    - **Addresses:** AC-1
    - Depends-on: none
""")

_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-T9
    kind: feature
    authority: human
    risk_tags: []
    ---

    ## Goals
    Test one role path.

    ## Acceptance Criteria
    - [ ] AC-1: something works
""")

_META = {
    "ticket": _KEY, "track": "XS", "kind": "feature", "phase": "build:work",
    "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
    "affected_modules": ["core/skills"], "risk_tags": [],
}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    tdir = tmp_path / ".klc" / "tickets" / _KEY
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text(_PLAN)
    (tdir / "spec.md").write_text(_SPEC)
    (tdir / "meta.json").write_text(json.dumps(_META))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_INLINE", raising=False)
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    return tmp_path


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                        "PATH": os.environ["PATH"], "HOME": str(repo)})


def test_task_step_card_has_no_read_impl_instruction(root):
    import artefacts
    card = artefacts.render_card(_KEY, "build", _META, step=1,
                                 mode=artefacts.CARD_MODE_DISPATCH)
    text = card.path.read_text(encoding="utf-8")
    assert "Before acting, read the role prompt" not in text
    assert "core/agents/impl.md" not in text
    assert "carried by the klc-impl subagent definition" in text

    paste = artefacts.render_card(_KEY, "build", _META, step=1,
                                  mode=artefacts.CARD_MODE_PASTE)
    ptext = paste.path.read_text(encoding="utf-8")
    assert "Before acting, read the role prompt" in ptext
    assert "core/agents/impl.md" in ptext


def test_headless_build_sends_impl_prompt_once(root, monkeypatch):
    import build_orchestrator as bo
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import klc114_helpers as h
    h.pin_step_state(monkeypatch, [1])   # KLC-174: dispatch commits nothing, pin step state
    calls = []

    def dispatch(phase_id, prompt_path, out_path, *, inputs=None, track=None, **kw):
        calls.append((phase_id, Path(prompt_path), inputs))
        return 0

    assert bo.run_build(_KEY, dispatch=dispatch) == 0
    phase, prompt, inputs = calls[0]
    assert phase == "build"
    assert str(prompt).endswith("core/agents/impl.md")
    assert inputs["brief"] == bo._brief_path(_KEY, 1)

    # fix pass: blocking findings -> fix dispatch also carries impl.md + brief input
    from findings import Finding
    calls.clear()
    blocking = [Finding(rule_name="r", severity="HIGH", file="a.py", line=1,
                        title="t", body="b", fix=None, reviewer="x")]
    seq = iter([blocking, []])
    monkeypatch.setattr(bo, "_run_reviewer", lambda *a, **kw: next(seq))
    monkeypatch.setattr(bo, "should_review", lambda meta: True)
    assert bo._per_step_gate(_KEY, 1, _META, dispatch) is True
    fix_calls = [c for c in calls if c[0] == "build"]
    assert fix_calls, "fix pass not dispatched"
    _, fprompt, finputs = fix_calls[0]
    assert str(fprompt).endswith("core/agents/impl.md")
    assert finputs["brief"] == bo._fix_brief_path(_KEY, 1)


def test_per_step_review_receives_step_diff(root, monkeypatch):
    import build_orchestrator as bo
    monkeypatch.chdir(root)
    _git(root, "init", "-q")
    (root / "f.txt").write_text("base\n")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "base")
    seen = {}

    def dispatch(phase_id, prompt_path, out_path, *, inputs=None, track=None, **kw):
        seen["pkg"] = Path(inputs["step package"]).read_text(encoding="utf-8")
        return 0

    # zero step commits: no diff section, nothing raises
    bo._run_reviewer(_KEY, 1, dispatch, track="M")
    assert "## step-1 diff" not in seen["pkg"]

    (root / "f.txt").write_text("base\nCHANGED-LINE\n")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", f"{_KEY} step-1: first step")
    bo._run_reviewer(_KEY, 1, dispatch, track="M")
    assert "## step-1 diff" in seen["pkg"]
    assert "+CHANGED-LINE" in seen["pkg"]


# --- KLC-172 review round 1 --------------------------------------------------

def _seed_findings(root):
    tdir = root / ".klc" / "tickets" / _KEY
    (tdir / "impl-plan-review-findings.json").write_text(json.dumps({"findings": [
        {"rule_name": "rule-x", "severity": "HIGH", "file": "a.py", "line": 3,
         "title": "card-finding-one", "body": "b", "fix": "f",
         "ref": "AC-1", "ac": ""},
        {"rule_name": "rule-y", "severity": "LOW", "file": "b.py", "line": 4,
         "title": "card-finding-other", "body": "b", "fix": "f",
         "ref": "AC-9", "ac": ""}]}))


@pytest.mark.parametrize("mode", ["CARD_MODE_DISPATCH", "CARD_MODE_PASTE"])
def test_step_card_carries_the_step_findings(root, mode):
    import artefacts
    _seed_findings(root)
    card = artefacts.render_card(_KEY, "build", _META, step=1,
                                 mode=getattr(artefacts, mode))
    text = card.path.read_text(encoding="utf-8")
    assert "## Review findings for this step" in text
    assert "card-finding-one" in text
    assert "card-finding-other" not in text


def test_step_card_without_findings_says_none(root):
    import artefacts
    card = artefacts.render_card(_KEY, "build", _META, step=1)
    sec = card.path.read_text(encoding="utf-8").split("## Review findings for this step", 1)[1]
    assert "(none)" in sec


def test_dispatch_card_intro_does_not_say_read_role_prompt_below(root):
    import artefacts
    d = artefacts.render_card(_KEY, "build", _META, step=1,
                              mode=artefacts.CARD_MODE_DISPATCH).path.read_text(encoding="utf-8")
    assert "Read the role prompt below" not in d
    p = artefacts.render_card(_KEY, "build", _META, step=1,
                              mode=artefacts.CARD_MODE_PASTE).path.read_text(encoding="utf-8")
    assert "Read the role prompt below" in p


def test_step_diff_is_per_commit_and_skips_interleaved_commits(root, monkeypatch):
    import build_orchestrator as bo
    monkeypatch.chdir(root)
    _git(root, "init", "-q")
    for name in ("f.txt", "g.txt", "h.txt"):
        (root / name).write_text("base\n")
    _git(root, "add", "f.txt", "g.txt", "h.txt")
    _git(root, "commit", "-q", "-m", "base")
    for name, line, subject in (("f.txt", "F-CHANGE", f"{_KEY} step-1: first step"),
                                ("g.txt", "G-OTHER-STEP", f"{_KEY} step-2: second step"),
                                ("h.txt", "H-FOLLOWUP", f"{_KEY} step-1: follow-up")):
        (root / name).write_text(f"base\n{line}\n")
        _git(root, "add", name)
        _git(root, "commit", "-q", "-m", subject)
    diff = bo._step_diff(_KEY, 1)
    assert "+F-CHANGE" in diff and "+H-FOLLOWUP" in diff
    assert "G-OTHER-STEP" not in diff


def test_compose_prompt_fence_outgrows_nested_fences(tmp_path):
    import runner
    prompt = tmp_path / "p.md"
    prompt.write_text("role\n")
    brief = tmp_path / "brief.md"
    brief.write_text("intro\n```python\nx = 1\n````\nafter\n")
    text = runner._compose_prompt(prompt, {"brief": brief})
    assert "\n`````\nintro" in text and text.count("\n`````\n") == 2
    plain = tmp_path / "plain.md"
    plain.write_text("no fences")
    assert "\n```\nno fences\n```\n" in runner._compose_prompt(prompt, {"x": plain})
    d = runner._compose_prompt(prompt, {"diff": plain})
    assert "\n```diff\nno fences\n```\n" in d
