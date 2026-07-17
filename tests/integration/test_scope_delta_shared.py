"""KLC-066 step-3 — scope_delta shared-file bucket routes to drift, not the
expansion hard-fail (AC-5). A utility edit must warn, not block; an owned
out-of-scope edit must still hard-fail."""
import json
import sys
from pathlib import Path

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import scope_delta as sd  # noqa: E402


MODULES = {
    "modules": [
        {"name": "core/skills", "path": "core/skills/"},
        {"name": "intake", "path": "core/phases/intake"},
        {"name": "routing", "path": "core/routing"},
    ],
    "files": {
        # a shared utility file, owned by nobody as primary
        "core/common/paths.py": {"primary_module": None,
                                 "member_of": ["intake", "routing"]},
    },
}


def test_bucket_changed_splits_shared_from_owned():
    """_bucket_changed puts shared files in shared_touched, owned in owned."""
    owned, shared, unknown = sd._bucket_changed(
        ["core/phases/intake.py", "core/common/paths.py", "vendor/x.py"],
        MODULES,
    )
    assert owned == ["intake"]                      # owned file → expansion path
    assert shared == ["intake", "routing"]          # shared file → drift path
    assert unknown == ["vendor/x.py"]               # orphan → expansion path


def _run_compare(monkeypatch, tmp_path, changed, planned):
    """Drive scope_delta.compare() with a stubbed git diff + modules.json."""
    idx = tmp_path / "index"
    idx.mkdir()
    (idx / "modules.json").write_text(json.dumps(MODULES), encoding="utf-8")
    monkeypatch.setattr(sd, "klc_index_dir", lambda: idx)
    monkeypatch.setattr(sd, "_git_changed_files", lambda root: list(changed))
    monkeypatch.setattr(sd, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sd._lc, "read_meta",
                        lambda t: {"affected_modules": list(planned)})
    return sd.compare("KLC-066")


def test_shared_edit_is_drift_not_expansion(monkeypatch, tmp_path):
    """A shared-file edit surfaces as drift (warning), never expansion."""
    d = _run_compare(monkeypatch, tmp_path,
                     changed=["core/common/paths.py"], planned=["intake"])
    assert d["expansion"] == []                      # NOT a hard-fail
    assert "routing" in d["drift"]                   # surfaced as a warning
    assert set(d["shared_touched"]) == {"intake", "routing"}


def test_owned_out_of_scope_edit_still_hard_fails(monkeypatch, tmp_path):
    """A non-shared owned file outside the plan still triggers expansion."""
    d = _run_compare(monkeypatch, tmp_path,
                     changed=["core/routing/router.py"], planned=["intake"])
    assert "routing" in d["expansion"]               # hard-fail preserved
    assert d["shared_touched"] == []


def test_orphan_file_still_expansion(monkeypatch, tmp_path):
    """A file under no module (orphan) is still expansion (hard-fail)."""
    d = _run_compare(monkeypatch, tmp_path,
                     changed=["vendor/thing.py"], planned=["intake"])
    assert "vendor/thing.py" in d["unknown_files"]
    assert d["expansion"] == ["vendor/thing.py"]
