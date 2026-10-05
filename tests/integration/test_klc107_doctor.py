#!/usr/bin/env python3
"""KLC-107 steps 1/2/9 — doctor's index-freshness, index-views,
index-degraded, project-tools and index-hook checks, plus the --json schema.
Fixture repositories, real `klc doctor` subprocess invocations.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests._env import require_skills_executable  # noqa: E402

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent
KLC = FRAMEWORK_ROOT / "scripts" / "klc"
sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))

_skills_executable = require_skills_executable()


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=15)


def _head(repo: Path) -> str:
    return _run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _commit(repo: Path, name: str, content: str = "x") -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _run_git(repo, "add", name)
    _run_git(repo, "commit", "-m", f"commit {name}")
    return _head(repo)


def _make_repo(tmp_path: Path, *, with_last_run: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "t@t.com")
    _run_git(repo, "config", "user.name", "T")
    first = _commit(repo, "seed.txt")

    klc = repo / ".klc"
    (klc / "index").mkdir(parents=True)
    (klc / "config").mkdir(parents=True)
    (klc / "logs").mkdir(parents=True)
    shutil.copy(FRAMEWORK_ROOT / "config" / "phases.yml", klc / "config" / "phases.yml")
    shutil.copy(FRAMEWORK_ROOT / "config" / "models.yml", klc / "config" / "models.yml")
    (klc / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")

    if with_last_run:
        (klc / "index" / ".last-run").write_text(first + "\n", encoding="utf-8")
    return repo


def _write_views(repo: Path, *, empty: bool = False) -> None:
    # KLC-108 review round 1, MEDIUM (D-108-10): token_idf.json joined the
    # required view set in index_health.VIEWS (later demoted to an optional,
    # warn-only view — see test_missing_token_idf_view_warns_not_fails below
    # for the pre-KLC-108-index regression case this fixture no longer
    # exercises). Every "fresh, fully-built index" fixture in this file now
    # carries it, matching what `klc init`/`klc update` produce today.
    index_dir = repo / ".klc" / "index"
    for name in ("inventory.json", "test_map.json", "file_roles.json",
                "module_edges.json", "symbol_usage.json", "token_idf.json"):
        (index_dir / name).write_text("{}" if empty else '{"a": 1}', encoding="utf-8")


def _run_doctor(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(KLC), "doctor", *extra],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=60,
    )


@_skills_executable
class TestIndexFreshness(unittest.TestCase):
    """AC-1: `klc doctor`'s index-freshness check."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-doctor-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_index_freshness_fails_when_last_run_behind_head(self):
        """AC-1: .last-run behind HEAD by three commits FAILs, naming both
        short SHAs, the commit distance, and the literal repair command."""
        repo = _make_repo(self.tmp_path)
        old_sha = (repo / ".klc" / "index" / ".last-run").read_text().strip()
        _commit(repo, "f1.txt")
        _commit(repo, "f2.txt")
        head_sha = _commit(repo, "f3.txt")
        _write_views(repo)

        r = _run_doctor(repo)
        self.assertIn("FAIL index-freshness", r.stdout)
        self.assertIn(old_sha[:8], r.stdout)
        self.assertIn(head_sha[:8], r.stdout)
        self.assertIn("3 commit(s) apart", r.stdout)
        self.assertIn("klc update", r.stdout)
        self.assertIn("DOCTOR_FAIL", r.stdout)
        self.assertNotEqual(r.returncode, 0)

    def test_index_freshness_fails_symmetrically_when_head_behind_last_run(self):
        """Edge case from the test-plan: HEAD behind .last-run (e.g. after a
        hard reset) is still a mismatch under AC-1's "the two values differ"."""
        repo = _make_repo(self.tmp_path)
        _commit(repo, "f1.txt")
        newer_sha = _commit(repo, "f2.txt")
        (repo / ".klc" / "index" / ".last-run").write_text(newer_sha + "\n",
                                                            encoding="utf-8")
        _run_git(repo, "reset", "--hard", "HEAD~1")
        _write_views(repo)

        r = _run_doctor(repo)
        self.assertIn("FAIL index-freshness", r.stdout)
        self.assertIn("commit(s) apart", r.stdout)

    def test_index_freshness_warns_when_never_initialised(self):
        """D-003 / Q-007: absent `.last-run` WARNs, not FAILs — `klc init`
        never ran, which is a different diagnosis from a stale index."""
        repo = _make_repo(self.tmp_path, with_last_run=False)
        r = _run_doctor(repo)
        self.assertIn("WARN index-freshness", r.stdout)
        self.assertIn(".last-run", r.stdout)
        self.assertIn("DOCTOR_OK", r.stdout)
        self.assertEqual(r.returncode, 0)


@_skills_executable
class TestIndexViews(unittest.TestCase):
    """AC-2: `klc doctor`'s index-views check."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-doctor-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_index_views_check_reports_missing_and_empty(self):
        """AC-2: absent, unparseable and empty-collection states are three
        distinct reasons, each naming the offending filename."""
        repo = _make_repo(self.tmp_path)
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        index_dir = repo / ".klc" / "index"
        # inventory.json missing, test_map.json unparseable, file_roles.json
        # empty object, module_edges.json empty array, symbol_usage.json valid.
        (index_dir / "test_map.json").write_text("{not json", encoding="utf-8")
        (index_dir / "file_roles.json").write_text("{}", encoding="utf-8")
        (index_dir / "module_edges.json").write_text("[]", encoding="utf-8")
        (index_dir / "symbol_usage.json").write_text('{"ok": true}', encoding="utf-8")

        r = _run_doctor(repo)
        self.assertIn("FAIL index-views", r.stdout)
        self.assertIn("inventory.json: missing", r.stdout)
        self.assertIn("test_map.json: unparseable", r.stdout)
        self.assertIn("file_roles.json: empty", r.stdout)
        self.assertIn("module_edges.json: empty", r.stdout)
        self.assertNotIn("symbol_usage.json:", r.stdout)
        self.assertIn("klc update --force", r.stdout)


def _chmod_framework_scripts_executable():
    """Temporarily +x every non-underscore `core/skills/*.py` and
    `core/phases/*.py` file in the REAL checked-out framework (not a copy —
    `doctor.py`'s `skills-executable`/`phase-scripts-executable` checks
    resolve their own directory from `Path(__file__)`, so they always inspect
    THIS checkout regardless of which fixture repo `_run_doctor` points
    PROJECT_ROOT at). Returns the list of `(path, original_mode)` pairs to
    restore. Mirrors the reviewer's own reproduction exactly (round 1, MEDIUM
    finding on `core/skills/index_health.py:22`), since `require_skills_executable`
    would otherwise mask any doctor-subprocess assertion in this environment
    (skill files ship at git mode 100644 on a fresh checkout)."""
    changed: list[tuple[Path, int]] = []
    for d in (FRAMEWORK_ROOT / "core" / "skills", FRAMEWORK_ROOT / "core" / "phases"):
        for p in d.glob("*.py"):
            if p.name.startswith("_") or p.name == "__init__.py":
                continue
            mode = p.stat().st_mode
            if not (mode & 0o111):
                changed.append((p, mode))
                p.chmod(mode | 0o111)
    return changed


def _restore_modes(changed: list[tuple[Path, int]]) -> None:
    for p, mode in changed:
        p.chmod(mode)


class TestIndexViewsOptionalTokenIdf(unittest.TestCase):
    """Review round 1, MEDIUM (D-108-10): `token_idf.json` is a KLC-108
    addition to `index_health.VIEWS`; an index built before this ticket never
    had it. Its absence must WARN, never hard-FAIL `klc doctor`'s
    `index-views` check — otherwise every pre-existing project starts
    reporting a hard FAIL immediately after pulling this ticket's code, until
    `klc update --force` is run. Defined OUTSIDE the `@_skills_executable`
    skip guard and does its own (restored) chmod, so this regression is
    provable in an environment where framework scripts ship without +x."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc108-doctor-idf-")
        self.tmp_path = Path(self.tmpdir)
        self.changed = _chmod_framework_scripts_executable()

    def tearDown(self):
        _restore_modes(self.changed)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_token_idf_view_warns_not_fails(self):
        """AC-8 review round 1 fix (D-108-10): token_idf.json absence must
        WARN, not FAIL, index-views — an index built before this ticket
        never had the file."""
        repo = _make_repo(self.tmp_path)
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        index_dir = repo / ".klc" / "index"
        # the pre-KLC-108 view set: everything EXCEPT token_idf.json.
        for name in ("inventory.json", "test_map.json", "file_roles.json",
                    "module_edges.json", "symbol_usage.json"):
            (index_dir / name).write_text('{"a": 1}', encoding="utf-8")
        self.assertFalse((index_dir / "token_idf.json").exists())

        # Only the index-views TAG is asserted, not the whole-process exit
        # code: this sandbox's checkout has an unrelated, pre-existing gap
        # (several core/skills/*.py files ship without a shebang line, which
        # a bare chmod +x cannot fix and which is out of KLC-108's scope) that
        # independently fails the `skills-executable` check regardless of
        # this fix. That is why `require_skills_executable()`'s class-level
        # skip guard exists for the OTHER tests in this file; this test
        # bypasses it deliberately (via chmod) to prove the index-views
        # behaviour specifically, not the aggregate doctor verdict.
        r = _run_doctor(repo)
        self.assertIn("WARN index-views", r.stdout)
        self.assertNotIn("FAIL index-views", r.stdout)
        self.assertIn("token_idf.json", r.stdout)

        r_strict = _run_doctor(repo, "--strict")
        self.assertIn("FAIL index-views", r_strict.stdout)

    def test_present_token_idf_view_still_passes_clean(self):
        """AC-8 regression guard: a FRESH index (all six files, including
        token_idf.json) must still report a clean PASS, not a WARN — the
        optional-view demotion only softens ABSENCE, it must not downgrade a
        fully-populated index's result."""
        repo = _make_repo(self.tmp_path)
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        _write_views(repo)
        r = _run_doctor(repo)
        self.assertIn("PASS index-views", r.stdout)
        self.assertNotIn("WARN index-views", r.stdout)
        self.assertNotIn("FAIL index-views", r.stdout)


@_skills_executable
class TestIndexDegraded(unittest.TestCase):
    """AC-3: `klc doctor`'s index-degraded check."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-doctor-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_index_degraded_check_branches(self):
        """AC-3, superseded by KLC-106 (this module's own docstring: "gains
        teeth when KLC-106 lands"): (a) a REAL KLC-106 coverage verdict
        carrying `degraded: true` in a persisted artifact's own `errors[]`
        WARNs (never FAILs — KLC-106 AC-15 is explicitly warn-only, with
        escalation to a hard failure staying KLC-107's) naming the builder;
        two offending builders in two different artifacts are both named;
        (b) no artifact carries a coverage verdict at all PASSes with the
        explicit note."""
        repo = _make_repo(self.tmp_path)
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        _write_views(repo)
        index_dir = repo / ".klc" / "index"
        (index_dir / "inventory.json").write_text(json.dumps({"errors": [
            {"builder": "inventory:python", "artifact": "inventory.json",
             "metric": "files-with-symbols", "observed": 1, "universe": 20,
             "ratio": 0.05, "threshold": 0.25, "degraded": True,
             "reason": "madge missing"},
        ]}), encoding="utf-8")
        (index_dir / "test_map.json").write_text(json.dumps({"errors": [
            {"builder": "dep_graph:import-graph.py", "artifact": "depgraph.json",
             "metric": "node-coverage", "observed": 0, "universe": 5,
             "ratio": 0.0, "threshold": 0.25, "degraded": True, "reason": "timeout"},
        ]}), encoding="utf-8")

        r = _run_doctor(repo)
        self.assertIn("WARN index-degraded", r.stdout)
        self.assertNotIn("FAIL index-degraded", r.stdout)
        self.assertIn("inventory:python", r.stdout)
        self.assertIn("dep_graph:import-graph.py", r.stdout)

    def test_index_degraded_passes_when_no_degradation_metadata_present(self):
        repo = _make_repo(self.tmp_path)
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        _write_views(repo)
        r = _run_doctor(repo)
        self.assertIn("PASS index-degraded", r.stdout)
        self.assertIn("degradation metadata is not present", r.stdout)


class TestProjectToolsWarn(unittest.TestCase):
    """AC-4 (revised by KLC-178 AC-9): `project-tools` says so out loud but is
    informational: never WARN, never FAIL, not even under --strict."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-doctor-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_project_tools_informational_when_deps_absent(self):
        """No project-deps.json → an informational line naming the file;
        the same fixture under --strict still does not fail on it."""
        repo = _make_repo(self.tmp_path)
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        _write_views(repo)
        self.assertFalse((repo / ".klc" / "index" / "project-deps.json").exists())

        r = _run_doctor(repo)
        self.assertIn("PASS project-tools", r.stdout)
        self.assertIn("project-deps.json", r.stdout)

        r_strict = _run_doctor(repo, "--strict")
        self.assertIn("PASS project-tools", r_strict.stdout)
        self.assertNotIn("FAIL project-tools", r_strict.stdout)

    @_skills_executable
    def test_project_tools_does_not_change_the_exit_code(self):
        """Exit-code half of the pin: needs the skills +x bit, the text half
        above does not (review round 1, F-009: it must run in every checkout)."""
        repo = _make_repo(self.tmp_path)
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        _write_views(repo)
        self.assertEqual(_run_doctor(repo).returncode, 0)


def _write_settings(repo: Path, mode: str, location: str) -> None:
    (repo / ".klc" / "config" / "settings.yml").write_text(
        f"index:\n  hook_mode: {mode}\n  hook_location: {location}\n",
        encoding="utf-8")


class TestIndexHook(unittest.TestCase):
    """AC-5: doctor's index-hook check reads the mode/location settings
    recorded, and nothing else (AC-17 single-source-of-truth)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-doctor-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    _counter = 0

    def _fresh_repo(self):
        TestIndexHook._counter += 1
        repo = _make_repo(self.tmp_path / f"case{TestIndexHook._counter}")
        (repo / ".klc" / "index" / ".last-run").write_text(_head(repo) + "\n",
                                                            encoding="utf-8")
        _write_views(repo)
        return repo

    def test_index_hook_check_by_recorded_mode(self):
        # direct + no klc invocation reachable -> FAIL
        repo = self._fresh_repo()
        hooks_dir = repo / ".git" / "hooks"
        _write_settings(repo, "direct", str(hooks_dir / "pre-commit"))
        r = _run_doctor(repo)
        self.assertIn("FAIL index-hook", r.stdout)
        self.assertIn(f"klc doctor --install {repo}", r.stdout)

        # direct + klc invocation present (the MARKER) -> PASS
        repo2 = self._fresh_repo()
        hooks_dir2 = repo2 / ".git" / "hooks"
        hooks_dir2.mkdir(parents=True, exist_ok=True)
        import hook_install as _hi
        (hooks_dir2 / "pre-commit").write_text(_hi.MARKER + "\n", encoding="utf-8")
        _write_settings(repo2, "direct", str(hooks_dir2 / "pre-commit"))
        r2 = _run_doctor(repo2)
        self.assertIn("PASS index-hook", r2.stdout)

        # snippet + manager config does NOT mention klc -> WARN
        repo3 = self._fresh_repo()
        (repo3 / ".husky").mkdir()
        _write_settings(repo3, "snippet", "husky")
        r3 = _run_doctor(repo3)
        self.assertIn("WARN index-hook", r3.stdout)
        self.assertIn(f"klc doctor --install {repo3}", r3.stdout)

        # snippet + manager config DOES mention klc -> PASS
        repo4 = self._fresh_repo()
        (repo4 / ".husky").mkdir()
        (repo4 / ".husky" / "pre-commit").write_text("klc update\n", encoding="utf-8")
        _write_settings(repo4, "snippet", "husky")
        r4 = _run_doctor(repo4)
        self.assertIn("PASS index-hook", r4.stdout)

        # disabled -> PASS regardless
        repo5 = self._fresh_repo()
        _write_settings(repo5, "disabled", "none")
        r5 = _run_doctor(repo5)
        self.assertIn("PASS index-hook", r5.stdout)

    def test_index_hook_check_trusts_settings_as_the_only_source(self):
        """AC-17 spy: settings says `disabled`, even though a real klc hook
        happens to be wired on disk — the check must still PASS on the
        recorded mode alone, not by independently detecting the hook."""
        repo = self._fresh_repo()
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        import hook_install as _hi
        (hooks_dir / "pre-commit").write_text(_hi.MARKER + "\n", encoding="utf-8")
        _write_settings(repo, "disabled", "none")
        r = _run_doctor(repo)
        self.assertIn("PASS index-hook", r.stdout)


@_skills_executable
class TestJsonSchema(unittest.TestCase):
    """AC-6: `klc doctor --json` keeps the existing result schema for the
    five new checks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-doctor-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_json_output_schema_for_five_new_checks(self):
        repo = _make_repo(self.tmp_path)
        old_sha = (repo / ".klc" / "index" / ".last-run").read_text().strip()
        _commit(repo, "extra.txt")   # FAIL index-freshness
        # index-views: FAIL (nothing written)
        # index-degraded: PASS (no metadata)
        # project-tools: PASS (informational)
        _write_settings(repo, "disabled", "none")  # index-hook: PASS

        r = _run_doctor(repo, "--json")
        data = json.loads(r.stdout)
        by_name = {c["check"]: c for c in data["checks"]}
        for name in ("index-freshness", "index-views", "index-degraded",
                    "index-hook", "project-tools"):
            self.assertIn(name, by_name, f"missing check {name}")
            entry = by_name[name]
            self.assertEqual(set(entry.keys()) - {"warn"}, {"check", "ok", "errors"})
            self.assertIsInstance(entry["ok"], bool)
            self.assertIsInstance(entry["errors"], list)


if __name__ == "__main__":
    unittest.main()
