import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.skills.models import load_models
from core.skills.model_guard import check_subagent_dispatch


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
