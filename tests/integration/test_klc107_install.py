#!/usr/bin/env python3
"""KLC-107 step-6 onward — settings for the hook mode / location / refresh
budget, hook-manager detection, and `klc install` wiring the hook.
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

_skills_executable = require_skills_executable()


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=15)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "t@t.com")
    _run_git(repo, "config", "user.name", "T")
    (repo / "seed.txt").write_text("x", encoding="utf-8")
    _run_git(repo, "add", "seed.txt")
    _run_git(repo, "commit", "-m", "seed")

    klc = repo / ".klc"
    (klc / "index").mkdir(parents=True)
    (klc / "config").mkdir(parents=True)
    (klc / "logs").mkdir(parents=True)
    shutil.copy(FRAMEWORK_ROOT / "config" / "phases.yml", klc / "config" / "phases.yml")
    shutil.copy(FRAMEWORK_ROOT / "config" / "models.yml", klc / "config" / "models.yml")
    (klc / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")
    return repo


def _run_doctor(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(KLC), "doctor", *extra],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=60,
    )


class TestSettingsHookKeys(unittest.TestCase):
    """AC-18: the settings key validator accepts the new hook keys.

    Skill-level (not through `klc doctor`): doctor's `config-validation`
    check calls `validate_config.validate_all()` with NO `config_dir`
    argument, so it always validates the FRAMEWORK's own `config/`
    directory, never a project's `.klc/config/` — a pre-existing property
    of doctor being install-level, not ticket-scoped. The validator itself
    (`validate_config.validate_settings(config_dir)`) is what actually
    carries the schema this AC is about, and it is parameterizable, so it
    is the correct and only target for this test."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-install-")
        self.tmp_path = Path(self.tmpdir)
        sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
        import validate_config as _vc
        self.vc = _vc

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_settings_validator_accepts_hook_keys_and_rejects_bad_value(self):
        """AC-18: the settings validator accepts the hook keys, rejects a bad value."""
        config_dir = self.tmp_path
        (config_dir / "settings.yml").write_text(
            "index:\n"
            "  hook_mode: snippet\n"
            "  hook_location: husky\n"
            "  refresh_budget_seconds: 30\n",
            encoding="utf-8",
        )
        warnings = self.vc.validate_settings(config_dir)
        self.assertEqual(warnings, [])

        (config_dir / "settings.yml").write_text(
            "index:\n"
            "  hook_mode: wired\n",
            encoding="utf-8",
        )
        warnings2 = self.vc.validate_settings(config_dir)
        self.assertEqual(len(warnings2), 1)
        self.assertIn("index.hook_mode", warnings2[0])
        self.assertIn("wired", warnings2[0])
        for mode in ("direct", "snippet", "disabled"):
            self.assertIn(mode, warnings2[0])


sys.path.insert(0, str(FRAMEWORK_ROOT / "core" / "skills"))
import hook_install as _hi  # noqa: E402


class TestHookDetection(unittest.TestCase):
    """AC-14/AC-19: hook-manager detection, git-resolved hooks directory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-install-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_install_detects_and_reports_hook_manager(self):
        """AC-14: install detects and reports the hook management mode."""
        cases = {
            "husky_only": (lambda r: (r / ".husky").mkdir(), "husky"),
            "lefthook_only": (lambda r: (r / "lefthook.yml").write_text("x"), "lefthook"),
            "pre_commit_only": (lambda r: (r / ".pre-commit-config.yaml").write_text("x"),
                                "pre-commit"),
            "none_detected": (lambda r: None, None),
        }
        for name, (setup, expect_manager) in cases.items():
            with self.subTest(case=name):
                repo = _make_repo(self.tmp_path / name)
                setup(repo)
                det = _hi.detect(repo)
                if expect_manager is None:
                    self.assertEqual(det["mode"], "direct")
                    self.assertEqual(det["manager"], "none")
                else:
                    self.assertEqual(det["mode"], "snippet")
                    self.assertEqual(det["manager"], expect_manager)
                self.assertEqual(det["also_detected"], [])

        # non-default core.hooksPath only
        with self.subTest(case="hooks_path_only"):
            repo = _make_repo(self.tmp_path / "hookspath")
            (repo / "custom-hooks").mkdir()
            _run_git(repo, "config", "core.hooksPath", "custom-hooks")
            det = _hi.detect(repo)
            self.assertEqual(det["mode"], "snippet")
            self.assertEqual(det["manager"], "hooksPath")

        # combined: two managers present — the DECLARED table order wins,
        # not filesystem/dict iteration order.
        with self.subTest(case="combined_lefthook_and_husky"):
            repo = _make_repo(self.tmp_path / "combined")
            (repo / ".husky").mkdir()
            (repo / "lefthook.yml").write_text("x", encoding="utf-8")
            det = _hi.detect(repo)
            self.assertEqual(det["mode"], "snippet")
            self.assertEqual(det["manager"], "lefthook")   # earlier in DETECTORS
            self.assertIn("husky", det["also_detected"])

            # Re-run several times — order must not depend on directory
            # listing / dict iteration, which can vary run to run.
            for _ in range(5):
                det2 = _hi.detect(repo)
                self.assertEqual(det2["manager"], "lefthook")

    def test_hooks_dir_resolved_via_git_not_assumed_path(self):
        """AC-19: hooks dir resolved through git, not an assumed path.

        Case (a): `.git` is a file (a separate-git-dir checkout, as a
        worktree or submodule would have) — the resolved hooks dir must be
        whatever `git rev-parse --git-path hooks` reports, not a hardcoded
        `.git/hooks`."""
        repo = self.tmp_path / "worktree_like"
        real_gitdir = self.tmp_path / "real.git"
        repo.mkdir(parents=True)
        r = subprocess.run(
            ["git", "init", f"--separate-git-dir={real_gitdir}", str(repo)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((repo / ".git").is_file())

        hooks_dir = _hi.resolve_hooks_dir(repo)
        expected = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        self.assertEqual(hooks_dir, (repo / expected).resolve())
        self.assertEqual(hooks_dir, (real_gitdir / "hooks").resolve())

    def test_hooks_dir_resolved_via_git_not_assumed_path_case_b(self):
        """AC-19: Case (b) (Q-005): a non-default `core.hooksPath` owned by
        another manager (a lefthook config file lives inside it) still falls
        back to the snippet mode of AC-16, rather than writing into that
        directory — a printed snippet survives the manager's next
        regeneration, a hook written there would not."""
        repo = _make_repo(self.tmp_path / "hookspath_managed")
        managed_dir = repo / "managed-hooks"
        managed_dir.mkdir()
        (managed_dir / "lefthook.yml").write_text("x", encoding="utf-8")
        _run_git(repo, "config", "core.hooksPath", "managed-hooks")
        det = _hi.detect(repo)
        self.assertEqual(det["mode"], "snippet")


def _make_executable(p: Path) -> None:
    import stat
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestHookFailsOpen(unittest.TestCase):
    """AC-15, C-006, finding F-3 / [!DECISION D-203]: a misconfigured hook
    must never block a commit."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-install-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_installed_shim_exits_zero_when_framework_root_is_missing(self):
        """AC-15, C-006: the installed shim fails open."""
        repo = _make_repo(self.tmp_path / "shim_missing")
        hooks_dir = repo / ".git" / "hooks"

        # (a) run the shim directly with KLC_FRAMEWORK_ROOT pointing at a
        # path that never existed.
        nonexistent_fw = self.tmp_path / "does_not_exist"
        action = _hi.write_hook(hooks_dir, nonexistent_fw)
        self.assertEqual(action, "written")
        r = subprocess.run(["sh", str(hooks_dir / "pre-commit")], cwd=str(repo),
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertIn(str(nonexistent_fw), r.stderr)

        # (b) a real `git commit` still succeeds after the framework
        # directory is renamed away.
        real_fw = self.tmp_path / "fake_fw"
        (real_fw / "hooks").mkdir(parents=True)
        fw_hook = real_fw / "hooks" / "pre-commit"
        fw_hook.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        _make_executable(fw_hook)
        _hi.write_hook(hooks_dir, real_fw)
        moved_away = self.tmp_path / "fake_fw_moved_away"
        real_fw.rename(moved_away)

        (repo / "new.txt").write_text("x", encoding="utf-8")
        _run_git(repo, "add", "new.txt")
        r2 = subprocess.run(["git", "commit", "-m", "after framework moved"],
                            cwd=str(repo), capture_output=True, text=True, timeout=15)
        self.assertEqual(r2.returncode, 0, r2.stderr)


class TestWriteHookIdempotentAndChains(unittest.TestCase):
    """AC-15: writes into a directory no manager owns, idempotent on
    re-run, preserves and chains a pre-existing non-klc hook, and does not
    swallow that prior hook's non-zero verdict."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-install-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fake_framework(self, name: str, marker: Path) -> Path:
        fw = self.tmp_path / name
        (fw / "hooks").mkdir(parents=True)
        hook = fw / "hooks" / "pre-commit"
        hook.write_text(f'#!/usr/bin/env sh\necho ran >> "{marker}"\nexit 0\n',
                        encoding="utf-8")
        _make_executable(hook)
        return fw

    def test_install_wires_plain_git_hook_idempotent_and_chains(self):
        """AC-15: writes the klc hook, idempotent re-run, chains a prior hook."""
        repo = _make_repo(self.tmp_path / "plain")
        hooks_dir = repo / ".git" / "hooks"
        marker = self.tmp_path / "marker.txt"
        fw = self._fake_framework("fw1", marker)

        action = _hi.write_hook(hooks_dir, fw)
        self.assertEqual(action, "written")
        before = (hooks_dir / "pre-commit").read_bytes()

        (repo / "a.txt").write_text("1", encoding="utf-8")
        _run_git(repo, "add", "a.txt")
        r = subprocess.run(["git", "commit", "-m", "trigger hook"], cwd=str(repo),
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(marker.exists(), "the klc hook did not run")
        self.assertEqual(marker.read_text(encoding="utf-8").count("ran"), 1)

        # Idempotent — a second install run leaves the file byte-identical.
        action2 = _hi.write_hook(hooks_dir, fw)
        self.assertEqual(action2, "unchanged")
        after = (hooks_dir / "pre-commit").read_bytes()
        self.assertEqual(before, after)

    def test_preexisting_non_klc_hook_is_chained_not_overwritten(self):
        """AC-15: a pre-existing non-klc hook is preserved by chaining."""
        repo = _make_repo(self.tmp_path / "chained")
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        prior = hooks_dir / "pre-commit"
        prior_marker = self.tmp_path / "prior_marker.txt"
        prior.write_text(
            f'#!/usr/bin/env sh\necho prior >> "{prior_marker}"\nexit 0\n',
            encoding="utf-8")
        _make_executable(prior)

        marker = self.tmp_path / "marker2.txt"
        fw = self._fake_framework("fw2", marker)
        action = _hi.write_hook(hooks_dir, fw)
        self.assertEqual(action, "chained")
        self.assertTrue((hooks_dir / _hi._CHAINED_NAME).exists())
        self.assertIn("prior", (hooks_dir / _hi._CHAINED_NAME).read_text(encoding="utf-8"))

        (repo / "b.txt").write_text("1", encoding="utf-8")
        _run_git(repo, "add", "b.txt")
        r = subprocess.run(["git", "commit", "-m", "trigger chained"], cwd=str(repo),
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(prior_marker.exists(), "the prior hook did not run")
        self.assertTrue(marker.exists(), "the klc hook did not run")

        # Idempotent after chaining too.
        action2 = _hi.write_hook(hooks_dir, fw)
        self.assertEqual(action2, "unchanged")

    def test_second_distinct_non_klc_hook_does_not_clobber_the_chain_slot(self):
        """review-fix (MEDIUM): a SECOND, DISTINCT non-klc hook landing at the
        `pre-commit` slot must never silently clobber `pre-commit.pre-klc` —
        Path.rename would otherwise replace it, permanently losing whatever
        was chained there before with no warning (AC-15's own wording:
        'an already-present non-klc hook is preserved by chaining rather than
        overwritten'). Simulates an out-of-band actor overwriting the shim
        directly with a different, unmarked hook after klc already chained
        hook A."""
        repo = _make_repo(self.tmp_path / "chain_collision")
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_a = hooks_dir / "pre-commit"
        hook_a.write_text("#!/usr/bin/env sh\necho hook-a\nexit 0\n", encoding="utf-8")
        _make_executable(hook_a)

        marker = self.tmp_path / "marker4.txt"
        fw = self._fake_framework("fw4", marker)
        action = _hi.write_hook(hooks_dir, fw)
        self.assertEqual(action, "chained")
        chained_path = hooks_dir / _hi._CHAINED_NAME
        hook_a_text = chained_path.read_text(encoding="utf-8")
        self.assertIn("hook-a", hook_a_text)

        # An out-of-band actor (not klc) overwrites the shim directly with a
        # DIFFERENT, unmarked hook B.
        pre_commit = hooks_dir / "pre-commit"
        pre_commit.write_text("#!/usr/bin/env sh\necho hook-b\nexit 0\n",
                              encoding="utf-8")
        _make_executable(pre_commit)

        with self.assertRaises(_hi.HookChainCollision):
            _hi.write_hook(hooks_dir, fw)

        # Hook A must survive, untouched, at the chain slot.
        self.assertEqual(chained_path.read_text(encoding="utf-8"), hook_a_text)

    def test_identical_second_hook_at_chain_slot_is_not_a_collision(self):
        """The SAME non-klc hook content landing at the chain slot twice (a
        genuinely idempotent re-chain) must not be treated as a collision."""
        repo = _make_repo(self.tmp_path / "chain_same")
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        prior_text = "#!/usr/bin/env sh\necho same-hook\nexit 0\n"
        pre_commit = hooks_dir / "pre-commit"
        pre_commit.write_text(prior_text, encoding="utf-8")
        _make_executable(pre_commit)

        marker = self.tmp_path / "marker5.txt"
        fw = self._fake_framework("fw5", marker)
        action = _hi.write_hook(hooks_dir, fw)
        self.assertEqual(action, "chained")

        # An out-of-band actor restores the IDENTICAL non-klc hook content at
        # the slot again.
        pre_commit.write_text(prior_text, encoding="utf-8")
        _make_executable(pre_commit)

        action2 = _hi.write_hook(hooks_dir, fw)
        self.assertEqual(action2, "chained")
        chained_path = hooks_dir / _hi._CHAINED_NAME
        self.assertEqual(chained_path.read_text(encoding="utf-8"), prior_text)

    def test_chained_prior_hook_failing_still_fails_the_commit(self):
        """AC-15: the fail-open guard must not swallow the PRIOR hook's verdict."""
        repo = _make_repo(self.tmp_path / "chained_fail")
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        prior = hooks_dir / "pre-commit"
        prior.write_text("#!/usr/bin/env sh\nexit 1\n", encoding="utf-8")
        _make_executable(prior)

        marker = self.tmp_path / "marker3.txt"
        fw = self._fake_framework("fw3", marker)
        _hi.write_hook(hooks_dir, fw)

        (repo / "c.txt").write_text("1", encoding="utf-8")
        _run_git(repo, "add", "c.txt")
        r = subprocess.run(["git", "commit", "-m", "should fail"], cwd=str(repo),
                           capture_output=True, text=True, timeout=15)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(marker.exists(), "klc hook must not run after a "
                         "failing prior hook")


class TestInstallSnippetAndRecording(unittest.TestCase):
    """AC-16/AC-17: through the real `klc install` entry point — no manager
    file touched, the snippet names the manager, and every branch records
    the decision in settings.yml."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="klc-test-klc107-install-")
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_install(self, project: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(KLC), "install", str(project)],
            capture_output=True, text=True, timeout=60,
        )

    def test_install_prints_snippet_and_leaves_manager_files_untouched(self):
        cases = {
            "husky": lambda r: (r / ".husky").mkdir(),
            "lefthook": lambda r: (r / "lefthook.yml").write_text("x", encoding="utf-8"),
            "pre-commit": lambda r: (r / ".pre-commit-config.yaml").write_text(
                "x", encoding="utf-8"),
        }
        for manager, setup in cases.items():
            with self.subTest(manager=manager):
                repo = _make_repo(self.tmp_path / manager)
                setup(repo)
                before_paths = {p for p in repo.rglob("*")
                                if p.is_file() and ".git" not in p.parts}
                before_hashes = {p: p.read_bytes() for p in before_paths}

                r = self._run_install(repo)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(manager, r.stdout)
                self.assertIn(f"{repo / '.klc' / 'bin' / 'klc'} update", r.stdout)

                for p, content in before_hashes.items():
                    self.assertEqual(p.read_bytes(), content,
                                     f"{p} was modified by klc install")
                # .mcp.json / .gitignore are pre-existing `klc install`
                # behaviour, unrelated to hook-manager wiring — excluded here.
                new_files = [p for p in repo.rglob("*")
                            if p.is_file() and ".git" not in p.parts
                            and ".klc" not in p.parts
                            and p.name not in (".gitignore", ".mcp.json")
                            and p not in before_paths]
                self.assertEqual(new_files, [], f"new manager-area files: {new_files}")

    def test_install_records_hook_mode_in_settings(self):
        cases = {
            "direct": lambda r: None,
            "snippet": lambda r: (r / ".husky").mkdir(),
        }
        for mode, setup in cases.items():
            with self.subTest(mode=mode):
                repo = _make_repo(self.tmp_path / f"record_{mode}")
                setup(repo)
                r = self._run_install(repo)
                self.assertEqual(r.returncode, 0, r.stderr)
                settings = (repo / ".klc" / "config" / "settings.yml").read_text(
                    encoding="utf-8")
                self.assertIn(f"hook_mode: {mode}", settings)
                self.assertIn("hook_location:", settings)

    def test_record_mode_preserves_a_hand_set_sibling_key_on_second_install(self):
        """review-fix (MEDIUM): record_mode() must MERGE into the managed
        `index:` block, not regenerate it from a fixed hook_mode/hook_location
        template — a user-set sibling key in the SAME block
        (`refresh_budget_seconds`, per config/settings.yml's own seed comment,
        which is explicitly NOT install-managed) must survive a second
        `klc install`."""
        repo = _make_repo(self.tmp_path / "preserve_sibling")
        r1 = self._run_install(repo)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        settings_path = repo / ".klc" / "config" / "settings.yml"
        settings = settings_path.read_text(encoding="utf-8")
        self.assertIn("hook_mode: direct", settings)

        # Hand-set a sibling key inside the SAME managed block (never the
        # commented seed template above it), mirroring an operator editing
        # settings.yml between installs.
        begin = settings.index("# BEGIN klc install")
        head, managed = settings[:begin], settings[begin:]
        managed = managed.replace(
            "  hook_location:",
            "  refresh_budget_seconds: 999\n  hook_location:", 1)
        settings_path.write_text(head + managed, encoding="utf-8")

        r2 = self._run_install(repo)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        after = settings_path.read_text(encoding="utf-8")
        self.assertIn("refresh_budget_seconds: 999", after,
                      "a hand-set sibling key was dropped by a second klc install")
        self.assertIn("hook_mode: direct", after)
        self.assertIn("hook_location:", after)


if __name__ == "__main__":
    unittest.main()
