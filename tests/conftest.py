"""Top-level pytest conftest: per-test cleanup for known order-dependence issues."""
import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

_SHARED_PATH = str(Path(__file__).resolve().parent.parent / "core" / "shared")
_SKILLS_PATH = str(Path(__file__).resolve().parent.parent / "core" / "skills")
_LIVE_GUARD_PATH = str(Path(__file__).resolve().parent / "shared" / "live_guard")
_TESTS_SHARED_PATH = str(Path(__file__).resolve().parent / "shared")


def pytest_configure(config):
    """KLC-136: register the live-`.klc`-write guard, unless an inner
    session already loaded it via `-p klc_live_guard_plugin` (the shim
    installed its core already; the plugin only needs registering once per
    process) or a run explicitly blocked it (`-p no:klc_live_guard_plugin` —
    the close-out's guard-overhead measurement uses exactly this)."""
    name = "klc_live_guard_plugin"
    if config.pluginmanager.is_blocked(name) or config.pluginmanager.has_plugin(name):
        return
    if _LIVE_GUARD_PATH not in sys.path:
        sys.path.insert(0, _LIVE_GUARD_PATH)
    import klc_live_guard_plugin
    config.pluginmanager.register(klc_live_guard_plugin, name=name)


@pytest.fixture(scope="session")
def fresh_index(tmp_path_factory):
    """KLC-136 AC-1/AC-2: a `.klc/index/` built ONCE per session from the
    current tree's tracked files, into a tmp mirror (D-216) — never read
    from the live `.klc/index/`. Session-scoped because the build itself
    takes a few seconds; every consumer treats the returned directory as
    read-only for the rest of the session."""
    for _p in (_TESTS_SHARED_PATH, _SKILLS_PATH):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import fresh_index as fresh_index_mod
    import _paths
    mirror_dir = tmp_path_factory.mktemp("fresh_index_mirror")
    return fresh_index_mod.build_fresh_index(_paths.framework_root(), mirror_dir)


@pytest.fixture
def live_index_state(request, tmp_path, monkeypatch, fresh_index):
    """KLC-136: points `PROJECT_ROOT` at a per-test stand-in project whose
    `.klc/index/` is `absent`, `stale` or `current` (`request.param`,
    indirect) — a copy derived from the session's `fresh_index`, never from
    the live one."""
    for _p in (_TESTS_SHARED_PATH,):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import fresh_index as fresh_index_mod
    state = request.param
    stand_in = tmp_path / "live-stand-in"
    fresh_index_mod.make_live_index_state(stand_in, state, fresh_index)
    monkeypatch.setenv("PROJECT_ROOT", str(stand_in))
    return stand_in


@pytest.fixture
def hermetic_project_root(request, tmp_path, monkeypatch):
    """KLC-136 AC-3: points `PROJECT_ROOT` at an EMPTY per-test tmp project
    — the group (b) implicit readers need no fixtures, just the guarantee
    that nothing resolves to a live or stand-in index. When the test ALSO
    uses `live_index_state`, that fixture is instantiated first (so its
    stand-in exists) and then overridden here, so the stand-in is built but
    never the effective `PROJECT_ROOT`."""
    if "live_index_state" in request.fixturenames:
        request.getfixturevalue("live_index_state")
    project = tmp_path / "hermetic-project"
    project.mkdir()
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    return project


@pytest.fixture
def no_index_reads(request, monkeypatch):
    """KLC-136: a read tracker over the stand-in's `.klc/index` (when
    `live_index_state` is active) and over `framework_root()/.klc/index`, in
    process and in Python subprocesses (`KLC_LIVE_GUARD_READ_ROOTS`/
    `KLC_LIVE_GUARD_READ_LOG`, `PYTHONPATH` prepended with the guard dir so a
    subprocess's `sitecustomize` picks the tracker up too). Returns a
    callable that lists the reads recorded so far FOR THE CURRENT TEST. When
    a read log is already configured (the AC-3 inner audit session), it
    reuses that log and ADDS its roots rather than replacing them."""
    if _LIVE_GUARD_PATH not in sys.path:
        sys.path.insert(0, _LIVE_GUARD_PATH)
    if _SKILLS_PATH not in sys.path:
        sys.path.insert(0, _SKILLS_PATH)
    import klc_live_guard as klg
    import _paths

    roots = [str(_paths.framework_root() / ".klc" / "index")]
    if "live_index_state" in request.fixturenames:
        stand_in = request.getfixturevalue("live_index_state")
        roots.append(str(Path(stand_in) / ".klc" / "index"))

    existing_log = os.environ.get("KLC_LIVE_GUARD_READ_LOG")
    if existing_log:
        log_path = existing_log
        existing_roots = [r for r in
                          os.environ.get("KLC_LIVE_GUARD_READ_ROOTS", "").split(os.pathsep)
                          if r]
        combined = existing_roots + [r for r in roots if r not in existing_roots]
    else:
        log_path = tempfile.mktemp(prefix="klc_no_index_reads_", suffix=".jsonl")
        combined = list(roots)
    monkeypatch.setenv("KLC_LIVE_GUARD_READ_LOG", log_path)
    monkeypatch.setenv("KLC_LIVE_GUARD_READ_ROOTS", os.pathsep.join(combined))
    existing_pp = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if _LIVE_GUARD_PATH not in existing_pp:
        monkeypatch.setenv("PYTHONPATH", os.pathsep.join([_LIVE_GUARD_PATH] + existing_pp))

    tracker = klg.track_reads(roots, log_path)
    test_id = klg.current_test_id()
    norm_roots = tuple(os.path.realpath(r) + os.sep for r in roots)

    def _reads():
        out = []
        for rec in klg.read_records(log_path):
            if rec.get("test") != test_id:
                continue
            p = rec.get("path", "")
            if any((p + os.sep).startswith(nr) for nr in norm_roots):
                out.append(rec)
        return out

    yield _reads
    klg.deactivate(tracker)


@pytest.fixture(autouse=True)
def _restore_project_root_env():
    """Snapshot $PROJECT_ROOT before each test and restore it after, no
    matter what the test did to `os.environ` directly.

    Several test files (Jira integration tests among them, e.g.
    test_jira_managed.py / test_jira_pull.py / test_jira_core.py, plus the
    KLC-057 multiuser fuzz suite) set `os.environ["PROJECT_ROOT"] = <tmp
    dir>` directly — without a `try/finally` and without the `monkeypatch`
    fixture — and never restore it. Once such a test's tmp dir is cleaned up,
    `PROJECT_ROOT` stays pointed at a DELETED directory for the rest of the
    pytest PROCESS, silently breaking any later test that resolves paths via
    `PROJECT_ROOT` without its own override (KLC-103: discovered via
    `test_detect_languages_real_key.py` / `test_klc103_rule_executor.py`
    intermittently failing only when the full suite runs them after one of
    these leaking tests). Two individual leaks were fixed directly
    (test_klc057_fuzz.py, tests/shared/test_paths.py); this fixture is the
    safety net for the rest — it guarantees process-wide isolation
    regardless of how many more such leaks exist today or get added later,
    without requiring an edit to every offending test file. It does not
    interfere with tests that already use `monkeypatch.setenv("PROJECT_ROOT",
    ...)` correctly: monkeypatch reverts its own change at its own teardown,
    so by the time this fixture's post-yield code runs, the value is already
    back to what it was when this fixture captured it — a harmless no-op
    restore in that case.
    """
    had = "PROJECT_ROOT" in os.environ
    original = os.environ.get("PROJECT_ROOT")
    yield
    if had:
        os.environ["PROJECT_ROOT"] = original
    else:
        os.environ.pop("PROJECT_ROOT", None)


@pytest.fixture(autouse=True)
def _restore_real_pyyaml():
    """Ensure sys.modules['yaml'] is real PyYAML (with safe_load) before each test.

    Multiple test files insert core/shared into sys.path at module level; a
    single sys.path.remove in jira_config.py's guard only removes the first
    copy, leaving the shadow findable for a bare `import yaml`.  This fixture
    pre-warms real PyYAML into sys.modules once, before the test body runs, so
    that both jira_config.load() and other callers always see the real module.
    """
    mod = sys.modules.get("yaml")
    if mod is not None and hasattr(mod, "safe_load"):
        # Already real PyYAML — nothing to do.
        yield
        return

    # Clear the shadow (if present) and pre-import real PyYAML with all
    # core/shared entries temporarily removed from sys.path.
    sys.modules.pop("yaml", None)
    removed_indices: list[int] = [
        i for i, p in enumerate(sys.path) if p == _SHARED_PATH
    ]
    # Remove in reverse order so indices stay valid
    for i in reversed(removed_indices):
        sys.path.pop(i)
    try:
        importlib.import_module("yaml")
    finally:
        # Restore core/shared entries at their original positions
        for i in removed_indices:
            sys.path.insert(i, _SHARED_PATH)
    yield


@pytest.fixture(autouse=True)
def _clear_lifecycle_meta_patches():
    """Clear `lifecycle._meta_patches` before and after every test (KLC-110
    review round 1, step-9a). It is a process-global dict keyed by ticket,
    staged by `phase_completion`'s persisting advisory producers (e.g. the
    KLC-110 retrieval-eval seam) and normally CONSUMED only by a successful
    `lifecycle.set_state`. A test that stages a patch — directly, or by
    exercising a code path that does — without driving a full successful
    transition would otherwise leak it into the NEXT test that reuses the
    same ticket key in the same pytest process: the same class of
    process-global leak `_restore_project_root_env` above guards against,
    for the same reason (module-global state outliving the test that set
    it). This replaces the manual per-test `_lc._apply_meta_patch(ticket, {})`
    drains some KLC-110 tests used to need."""
    if _SKILLS_PATH not in sys.path:
        sys.path.insert(0, _SKILLS_PATH)
    import lifecycle as _lc
    _lc._meta_patches.clear()
    yield
    _lc._meta_patches.clear()
