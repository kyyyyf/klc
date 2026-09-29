"""KLC-136 step-9 — AC-3 follow-on (found by the operator's AC-9
PROJECT_ROOT-unset full-suite run, 2026-09-29): every mode
`install_deps.main()` dispatches to first does an UNCONDITIONAL
`klc_dir().mkdir(parents=True, exist_ok=True)` / `log_init(...)` (itself
another `mkdir(exist_ok=True)`) BEFORE the mode-specific function runs.
`exist_ok=True` makes this invisible on a checkout where the target
directory already exists (D-204: no state change) — it silently CREATES
the guarded root the first time it does not. Confirmed live: the
operator's AC-9 unset run caught
`tests/test_install_deps.py::TestInstallDepsDispatcher::test_backward_compat`
doing exactly this against a fresh scratch clone's unset-PROJECT_ROOT
fallback root, because `TestInstallDepsDispatcher` never redirected
`PROJECT_ROOT` before calling `install_deps.main()`.

The fix (same commit as this test) is `setUp`/`tearDown` on
`TestInstallDepsDispatcher` itself, redirecting `PROJECT_ROOT` to a fresh
scratch dir for every test in that class — `unittest.TestCase` methods
cannot take the `monkeypatch` fixture as a parameter, so this is the
manual save/restore form of the same thing. This test proves that fix
holds even when the unset-PROJECT_ROOT fallback root would otherwise
resolve to a location that has never been touched (simulated by pointing
`_paths.framework_root` at a fresh `tmp_path`): because `setUp` sets
`PROJECT_ROOT` explicitly before `install_deps.main()` ever runs,
`project_root()` never falls through to `framework_root().parent` at all,
so the fallback root is never even consulted, regardless of where
`framework_root()` points.

Real-substrate: drives the real `TestInstallDepsDispatcher.setUp`/
`tearDown`, the real `install_deps.main()`, and a real
`klc_live_guard.Guard` — nothing mocked except the one dependency-check
function `TestInstallDepsDispatcher.test_backward_compat` itself already
mocks.

Review round 1 ext LOW: `tests/test_install_deps.py` itself puts
`FRAMEWORK_ROOT/core` on `sys.path` AT MODULE LEVEL (pre-existing, not
touched here) — with `core/` (not just `core/skills`) reachable, a bare
`import phases` elsewhere resolves to the `core/phases/` PACKAGE instead
of whatever it is meant to resolve to, breaking `phase_completion.py`'s own
attribute wiring for any test collected afterwards in the SAME session
(reproduced: `pytest test_klc136_install_deps_hermetic.py test_drift_review.py`
gave 3 failures in the latter, e.g. `test_records_findings_only_on_persist`
recording `seen == []` instead of `[False, True]`). The ORIGINAL version of
this file made that worse by ALSO importing `test_install_deps` at ITS OWN
module level (so the pollution landed at COLLECTION time, before any test
runs, rather than only when `TestInstallDepsDispatcher` is actually used).
The fix: `test_install_deps` is loaded via `importlib.util.spec_from_file_location`
INSIDE the one test that needs it, with `sys.path` and `sys.modules`
snapshotted and restored in a `finally` — so this file causes zero
observable import-time side effects on any test collected before OR after
it in the same session.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GUARD_DIR = REPO_ROOT / "tests" / "shared" / "live_guard"
for _p in (str(GUARD_DIR), str(REPO_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc_live_guard as klg  # noqa: E402
import _paths  # noqa: E402


def _load_test_install_deps():
    """Loads tests/test_install_deps.py by file path, under its own
    private module name — never `sys.path.insert`s `core`/`scripts`/`tests`
    itself; the caller is responsible for whatever transient `sys.path`
    entries `install_deps`/`deps` need for the DURATION of the test, and
    for restoring `sys.path`/`sys.modules` afterwards."""
    path = REPO_ROOT / "tests" / "test_install_deps.py"
    spec = importlib.util.spec_from_file_location("_klc136_test_install_deps", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dispatcher_test_case_never_touches_the_unset_fallback_root(tmp_path, monkeypatch):
    """AC-3 follow-on: `TestInstallDepsDispatcher`'s `setUp`/`tearDown`
    redirect `PROJECT_ROOT` before any test method runs, so
    `install_deps.main()` never even consults the unset-`PROJECT_ROOT`
    fallback root — proven by pointing `_paths.framework_root` at a fresh
    location and confirming its (would-be) fallback stays untouched
    throughout a full `setUp`/test/`tearDown` cycle."""
    fake_framework_root = tmp_path / "framework"
    fake_framework_root.mkdir()
    fallback_klc = fake_framework_root.parent / ".klc"
    assert not fallback_klc.exists()

    monkeypatch.delenv("PROJECT_ROOT", raising=False)
    monkeypatch.setattr(_paths, "framework_root", lambda: fake_framework_root)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "probe_install_deps (call)")

    # Review round 1 ext LOW: snapshot sys.path AND sys.modules before
    # loading test_install_deps.py (which, at ITS OWN module level, still
    # puts core/ and scripts/ on sys.path — pre-existing, out of scope to
    # change here) — restored in the finally below regardless of what that
    # module (or install_deps/deps/phases underneath it) mutated, so this
    # file causes zero observable cross-test side effects.
    path_before = list(sys.path)
    modules_before = set(sys.modules)

    guard = klg.Guard(roots=[str(fallback_klc)], report_path=None)
    klg.activate(guard)
    try:
        tid_mod = _load_test_install_deps()
        case = tid_mod.TestInstallDepsDispatcher("test_backward_compat")
        case.setUp()
        try:
            with mock.patch("deps.project.check_project", return_value=0):
                import install_deps
                result = install_deps.main([])
            assert result == 0
        finally:
            case.tearDown()
        violations = guard.violations("probe_install_deps")
    finally:
        klg.deactivate(guard)
        sys.path[:] = path_before
        for name in set(sys.modules) - modules_before:
            del sys.modules[name]

    assert violations == [], violations
    assert not fallback_klc.exists(), (
        "install_deps.main([]), run through TestInstallDepsDispatcher's "
        "own setUp/tearDown, still created the unset-PROJECT_ROOT fallback "
        "root that did not exist before it ran")
