"""KLC-066 — planning_validate.py cross-artifact / self-consistency checks."""
import sys
from pathlib import Path

_skills = Path(__file__).parent.parent.parent / "core" / "skills"
sys.path.insert(0, str(_skills))
import planning_validate as pv  # noqa: E402


GOOD = {
    "modules": [
        {"name": "intake", "path": "core/phases/intake", "files": ["core/phases/intake/a.py"]},
        {"name": "routing", "path": "core/routing", "files": ["core/routing/r.py"]},
    ],
    "files": {
        "scripts/intake.py": {"primary_module": "intake"},
        "core/common/paths.py": {"primary_module": None,
                                 "member_of": ["intake", "routing"]},
    },
}


def test_clean_map_has_no_warnings():
    r = pv.validate(GOOD, files_list=["core/phases/intake/a.py", "scripts/intake.py"])
    assert r["warnings"] == []
    assert r["counts"]["shared_files"] == 1
    assert r["counts"]["orphans"] == 0


def test_unknown_module_reference_flagged():
    bad = {"modules": GOOD["modules"],
           "files": {"x.py": {"primary_module": "does_not_exist"}}}
    r = pv.validate(bad, files_list=[])
    assert any("unknown module" in w for w in r["warnings"])


def test_mislabelled_shared_file_flagged():
    bad = {"modules": GOOD["modules"],
           "files": {"x.py": {"primary_module": None, "member_of": ["intake"]}}}
    r = pv.validate(bad, files_list=[])
    assert any("member_of<2" in w for w in r["warnings"])


def test_duplicate_module_name_flagged():
    bad = {"modules": [
        {"name": "dup", "path": "a"}, {"name": "dup", "path": "b"}]}
    r = pv.validate(bad, files_list=[])
    assert any("duplicate module name" in w for w in r["warnings"])


def test_module_without_path_or_files_flagged():
    bad = {"modules": [{"name": "empty"}]}
    r = pv.validate(bad, files_list=[])
    assert any("no path and no files" in w for w in r["warnings"])


def test_orphan_detection_when_file_list_given():
    r = pv.validate(GOOD, files_list=["vendor/thing.py"])
    assert r["counts"]["orphans"] == 1
    assert any("orphan files" in w for w in r["warnings"])


def test_orphan_check_degrades_without_file_list():
    r = pv.validate(GOOD, files_list=None)
    assert any("orphan check skipped" in e for e in r["errors"])


def test_cli_exit_2_on_missing_modules(tmp_path):
    rc = pv.main(["--in-modules", str(tmp_path / "nope.json")])
    assert rc == 2


def test_cli_strict_exits_1_on_warnings(tmp_path):
    import json
    mp = tmp_path / "modules.json"
    mp.write_text(json.dumps(
        {"modules": [{"name": "empty"}]}), encoding="utf-8")
    assert pv.main(["--in-modules", str(mp)]) == 0            # non-strict: exit 0
    assert pv.main(["--in-modules", str(mp), "--strict"]) == 1  # strict: exit 1
