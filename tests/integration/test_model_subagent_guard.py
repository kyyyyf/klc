import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.models import load_models, ResolvedModel
from core.skills.model_guard import check_subagent_dispatch

_GUARD_SCRIPT = _FW_ROOT / "core" / "skills" / "model_guard.py"

# ---------------------------------------------------------------------------
# Minimal ticket fixture for orchestrator tests
# ---------------------------------------------------------------------------

_MINIMAL_PLAN = textwrap.dedent("""\
    ---
    ticket: KLC-GUARD
    kind: impl-plan
    ---
    ## step-1 — guard test step
    - **Goal:** placeholder
    - **Interfaces:** none
    - **Expected:** guard raises
    - **VERIFY:** pytest
    - **COMMIT:** test
    - **Affected:** none
    - Depends-on: none
    - **Code sketch:**
    ```python
    pass
    ```
""")

_MINIMAL_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-GUARD
    kind: tech
    authority: human
    risk_tags: []
    ---
    ## Goals
    Guard test.
    ## Acceptance Criteria
    - [ ] AC-1: guard rejects
    ## Approaches
    - Option A: minimal
    Picked: Option A — simplest
""")

_MINIMAL_META = json.dumps({
    "ticket": "KLC-GUARD",
    "track": "S",
    "kind": "tech",
    "phase": "build:work",
    "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
    "affected_modules": ["core/skills"],
    "risk_tags": [],
})


def _bad_resolved() -> ResolvedModel:
    """A ResolvedModel with empty model — no explicit mapping."""
    return ResolvedModel(
        role="coding", phase="build", track="S",
        provider="anthropic", model="",
        api_key_env=None, extra_args=[], source="default",
    )


def test_resolve_records_source():
    m = load_models()
    # 'review' is mapped in phase_roles per config/models.yml
    assert m.resolve("review", track="S").source in {"per_track", "phase_roles"}
    # a bogus phase falls through to defaults
    assert m.resolve("totally-unmapped-phase").source == "default"


def test_warns_on_default_dispatch():
    m = load_models()
    assert check_subagent_dispatch(m.resolve("totally-unmapped-phase")) is not None
    assert check_subagent_dispatch(m.resolve("review", track="S")) is None


def test_cli_exits_1_on_unmapped_phase():
    r = subprocess.run(
        [sys.executable, str(_GUARD_SCRIPT), "--phase", "totally-unmapped-phase"],
        capture_output=True, text=True, cwd=str(_FW_ROOT),
    )
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["source"] == "default"
    assert data["note"] is not None
    assert "explicit-model-missing" in data["note"]


def test_cli_exits_0_on_mapped_phase():
    r = subprocess.run(
        [sys.executable, str(_GUARD_SCRIPT), "--phase", "review", "--track", "S"],
        capture_output=True, text=True, cwd=str(_FW_ROOT),
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["source"] in {"per_track", "phase_roles"}
    assert data["note"] is None


# ---------------------------------------------------------------------------
# Step-3 RED: strict model guard tests (KLC-050)
# ---------------------------------------------------------------------------

def test_model_guard_strict_rejects():
    from core.skills.model_guard import require_subagent_model
    with pytest.raises(ValueError):
        require_subagent_model(None)
    with pytest.raises(ValueError):
        require_subagent_model(_bad_resolved())  # model=""


def test_runner_refuses_dispatch_without_model(tmp_path):
    """run_agent must raise/return non-zero and NEVER call the dispatcher when model is empty."""
    import core.skills.runner as _runner

    prompt = tmp_path / "prompt.md"
    prompt.write_text("test prompt")
    out = tmp_path / "out.md"

    mock_mc = MagicMock()
    mock_mc.resolve.return_value = _bad_resolved()
    mock_dispatcher = MagicMock(return_value=0)

    with patch.object(_runner, "load_models", return_value=mock_mc), \
         patch.dict(_runner._DISPATCH, {"anthropic": mock_dispatcher}):
        with pytest.raises(ValueError):
            _runner.run_agent("build", prompt, out, track="S")

    mock_dispatcher.assert_not_called()


def test_build_orchestrator_refuses_dispatch_without_model(tmp_path, monkeypatch):
    """run_build must refuse and NOT call the dispatch callback when model is empty."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    tdir = tmp_path / ".klc" / "tickets" / "KLC-GUARD"
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text(_MINIMAL_PLAN)
    (tdir / "spec.md").write_text(_MINIMAL_SPEC)
    (tdir / "meta.json").write_text(_MINIMAL_META)

    import build_orchestrator as _bo
    mock_mc = MagicMock()
    mock_mc.resolve.return_value = _bad_resolved()

    dispatch_calls = []

    def mock_dispatch(phase_id, prompt_path, out_path, *, track=None):
        dispatch_calls.append(phase_id)
        return 0

    with patch.object(_bo, "load_models", return_value=mock_mc):
        with pytest.raises(ValueError):
            _bo.run_build("KLC-GUARD", dispatch=mock_dispatch)

    assert dispatch_calls == [], "dispatch must NOT be called when model is empty"
