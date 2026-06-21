import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.skills.models import load_models
from core.skills.model_guard import check_subagent_dispatch

_FW_ROOT = Path(__file__).resolve().parents[2]
_GUARD_SCRIPT = _FW_ROOT / "core" / "skills" / "model_guard.py"


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
