"""tests/integration/test_klc109_test_writer_sample.py — KLC-109 review-fix
step-10 (D-109-8, code-review MEDIUM): behavioural coverage for
`test-writer.sample_existing_tests`, which had zero automated tests before
or after its step-7 rewrite from a hand-written glob list to a selection
over the shared file universe (KLC-105) filtered by the shared predicate
(KLC-109).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_WRITER = _FW_ROOT / "core" / "skills" / "test-writer.py"
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))


def _load_writer():
    spec = importlib.util.spec_from_file_location("test_writer_klc109", _WRITER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sample_existing_tests_selects_only_universe_tests_via_shared_predicate(tmp_path, monkeypatch):
    """AC-10/AC-12: sample_existing_tests selects only test paths out of the
    shared universe (a colocated go test beside its production file), never
    a production file, filtered to the given module prefixes."""
    tw = _load_writer()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "foo.go").write_text("package pkg\n", encoding="utf-8")
    (tmp_path / "pkg" / "foo_test.go").write_text("package pkg\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bar.py").write_text("# prod\n", encoding="utf-8")

    universe = {"pkg/foo.go", "pkg/foo_test.go", "src/bar.py"}
    monkeypatch.setattr(tw, "project_root", lambda: tmp_path)
    monkeypatch.setattr(tw._fu, "members", lambda root, structural=None: set(universe))

    result = tw.sample_existing_tests([tmp_path / "pkg", tmp_path / "src"])
    assert result == ["pkg/foo_test.go"], result


def test_sample_existing_tests_excludes_the_two_framework_modules(tmp_path, monkeypatch):
    """AC-10/AC-12 review-fix (D-109-8): core/skills/test_map.py and
    core/skills/test_conventions.py — which satisfy the bare python
    `test_*.py` basename glob with no sibling map.py/conventions.py beside
    them — must NOT be sampled as existing tests to imitate."""
    tw = _load_writer()
    skills = tmp_path / "core" / "skills"
    skills.mkdir(parents=True)
    (skills / "test_map.py").write_text("# real prod change, no map.py sibling\n", encoding="utf-8")
    (skills / "test_conventions.py").write_text("# real prod change, no conventions.py sibling\n",
                                                encoding="utf-8")
    (skills / "real_util.py").write_text("# prod\n", encoding="utf-8")

    universe = {"core/skills/test_map.py", "core/skills/test_conventions.py",
                "core/skills/real_util.py"}
    monkeypatch.setattr(tw, "project_root", lambda: tmp_path)
    monkeypatch.setattr(tw._fu, "members", lambda root, structural=None: set(universe))

    result = tw.sample_existing_tests([skills])
    assert result == [], result


def test_sample_existing_tests_is_deterministic(tmp_path, monkeypatch):
    """AC-10: two calls over the same universe return the same, sorted
    order."""
    tw = _load_writer()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.go").write_text("package pkg\n", encoding="utf-8")
    (tmp_path / "pkg" / "a_test.go").write_text("package pkg\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.go").write_text("package pkg\n", encoding="utf-8")
    (tmp_path / "pkg" / "b_test.go").write_text("package pkg\n", encoding="utf-8")

    universe = {"pkg/a.go", "pkg/a_test.go", "pkg/b.go", "pkg/b_test.go"}
    monkeypatch.setattr(tw, "project_root", lambda: tmp_path)
    monkeypatch.setattr(tw._fu, "members", lambda root, structural=None: set(universe))

    first = tw.sample_existing_tests([tmp_path / "pkg"])
    second = tw.sample_existing_tests([tmp_path / "pkg"])
    assert first == second == sorted(first)
    assert first == ["pkg/a_test.go", "pkg/b_test.go"]


def test_sample_existing_tests_empty_universe_returns_empty(tmp_path, monkeypatch):
    """AC-10: an empty universe (e.g. a fresh clone before any index run)
    yields an empty sample, never an exception."""
    tw = _load_writer()
    monkeypatch.setattr(tw, "project_root", lambda: tmp_path)
    monkeypatch.setattr(tw._fu, "members", lambda root, structural=None: set())

    assert tw.sample_existing_tests([tmp_path / "pkg"]) == []


def test_sample_existing_tests_respects_the_active_profile_table(tmp_path, monkeypatch):
    """AC-5/AC-10: sample_existing_tests reads its table through
    active_table(), so a profile-declared layout is honoured here exactly as
    it is everywhere else — a `*_check.go` basename a synthetic profile adds
    is recognised as a test ONLY under the extended table, proving the
    filter genuinely comes from active_table() and not a hidden fallback."""
    tw = _load_writer()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "foo.go").write_text("package pkg\n", encoding="utf-8")
    (tmp_path / "pkg" / "foo_check.go").write_text("package pkg\n", encoding="utf-8")

    universe = {"pkg/foo.go", "pkg/foo_check.go"}
    monkeypatch.setattr(tw, "project_root", lambda: tmp_path)
    monkeypatch.setattr(tw._fu, "members", lambda root, structural=None: set(universe))

    # Under the built-in table, `*_check.go` matches no go test_basenames glob.
    monkeypatch.setattr(tw._tc, "active_table", lambda: tw._tc.builtin_table())
    assert tw.sample_existing_tests([tmp_path / "pkg"]) == []

    extended = tw._tc.table_from_manifest({
        "test_conventions": {
            "extensions": [".go"],
            "test_dirs": [],
            "test_globs": ["*_check.go"],
            "stem_rules": [["*_check", "{head}"]],
        }
    })
    monkeypatch.setattr(tw._tc, "active_table", lambda: extended)
    assert tw.sample_existing_tests([tmp_path / "pkg"]) == ["pkg/foo_check.go"]
