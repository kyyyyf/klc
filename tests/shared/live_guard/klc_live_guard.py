"""KLC-136 — the live-`.klc`-write guard (standard library only).

This module is the process-wide core: a single `sys.addaudithook` dispatcher
that forwards every file-mutating event to whichever `Guard` (and
`ReadTracker`) instances are currently active in THIS process, plus the
primitives `klc_live_guard_plugin.py` (the pytest plugin) and
`sitecustomize.py` (the subprocess shim) build on.

Design notes (impl-plan.md step-2):

- **Judged by effect, not by the raw audit event (spec.md AC-6, F-013).**
  `sys.addaudithook` fires audit events BEFORE the underlying syscall runs,
  for every candidate call whether or not it actually changes anything (an
  `os.mkdir(existing_dir, exist_ok=True)` fires `os.mkdir` even though the
  directory is untouched). So a `Guard` never trusts the event alone: it
  snapshots `path_state()` the FIRST time it sees a `(test, path)` pair (the
  pre-state, captured before the syscall runs) and only reports a violation
  if the CURRENT state, read later when the test ends, differs from that
  snapshot. `path_state()` is identity-only (D-204): a directory's tuple
  never includes its mtime (so an idempotent `exist_ok=True` mkdir, or an
  `os.utime`/`os.chmod` that copytree applies to a directory it did not
  otherwise touch, cannot look like a change); a file's tuple adds size and
  mtime_ns (so a same-inode rewrite via `open(p, "w")` is still caught).
- **A guarded root's own writer identifies the current test by
  `$PYTEST_CURRENT_TEST`, read on EVERY event (impl-plan-review F-3), never
  cached at install time.** pytest sets and updates this env var itself,
  automatically, around every test phase (setup/call/teardown), in every
  pytest process it runs including a nested inner session. Reading it fresh
  on each event is what lets a single process-wide dispatcher correctly
  attribute writes to whichever test (outer or, in a nested pytest session,
  inner) is currently executing, with no separate "current test" tracking of
  our own to keep in sync.
- **A subprocess relays candidates through a report file, pre-state
  included.** A `Guard` configured with a `report_path` (the subprocess/shim
  case) appends one JSON line per candidate the moment it is observed,
  carrying the OBSERVED PRE-STATE alongside the path — because by the time
  the process that reads the report back evaluates `violations()`, the
  writing process has already exited and its own in-memory pre-state is
  gone. Recording the pre-state in the report line lets `violations()` apply
  the exact same "did the state actually change" test to a subprocess write
  as it does to an in-process one, so a false positive relayed through a
  subprocess (were one ever added) would be filtered exactly the same way.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from pathlib import Path

# --- D-203: the event table -----------------------------------------------

# Events whose EVERY path-like argument is a write candidate (both sides of
# a rename change; every argument order.rename/remove/rmdir/mkdir/chmod/utime
# names the one path touched).
_WRITE_BOTH = {
    "os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.truncate",
    "os.chmod", "os.utime", "shutil.rmtree", "shutil.move",
}

# Events where only the DESTINATION (never the source, which is merely being
# read) is a write candidate. `shutil.copyfile`/`shutil.copytree` fire this
# top-level event AND the underlying per-file `open`s; listening here too is
# what catches `os.symlink`/`os.link`, which never go through `open` at all.
_WRITE_DST = {
    "shutil.copyfile", "shutil.copytree", "os.symlink", "os.link",
}

_PHASE_SUFFIXES = (" (setup)", " (call)", " (teardown)")


def _strip_phase(test_id: str) -> str:
    if not test_id:
        return test_id
    for suffix in _PHASE_SUFFIXES:
        if test_id.endswith(suffix):
            return test_id[: -len(suffix)]
    return test_id


def current_test_id() -> str:
    """The nodeid pytest is CURRENTLY executing, phase suffix stripped.

    Read fresh on every call (impl-plan-review F-3) — never cached — because
    pytest keeps `$PYTEST_CURRENT_TEST` current for the whole life of a
    process, including a nested inner pytest session.
    """
    return _strip_phase(os.environ.get("PYTEST_CURRENT_TEST", ""))


def _as_path(value) -> str | None:
    if isinstance(value, (str, bytes, os.PathLike)):
        try:
            return os.fspath(value)
        except Exception:
            return None
    return None


def _is_write_open(mode, flags) -> bool:
    if mode:
        return any(c in mode for c in "wax+")
    if isinstance(flags, int) and flags >= 0:
        accmode = flags & getattr(os, "O_ACCMODE", 0o3)
        if accmode in (os.O_WRONLY, os.O_RDWR):
            return True
        for bit_name in ("O_CREAT", "O_TRUNC", "O_APPEND", "O_EXCL"):
            bit = getattr(os, bit_name, 0)
            if bit and (flags & bit):
                return True
    return False


def _candidate_paths(event: str, args: tuple):
    """D-203: yields every path a write-type event might touch."""
    try:
        if event == "open":
            path, mode, flags = args
            if _is_write_open(mode, flags):
                p = _as_path(path)
                if p is not None:
                    yield p
            return
        if event in _WRITE_BOTH:
            for a in args:
                p = _as_path(a)
                if p is not None:
                    yield p
            return
        if event in _WRITE_DST:
            if len(args) > 1:
                p = _as_path(args[1])
                if p is not None:
                    yield p
    except Exception:
        return


def _read_paths(event: str, args: tuple):
    """The read-mode half of the `open` event, for `track_reads`."""
    try:
        if event != "open":
            return
        path, mode, flags = args
        if _is_write_open(mode, flags):
            return
        p = _as_path(path)
        if p is not None:
            yield p
    except Exception:
        return


def path_state(p) -> tuple | None:
    """D-204: an identity-only snapshot of a path.

    None means "does not exist" (or could not be determined — see below).
    A directory's tuple is (kind, inode, device) only — no mtime and no
    mode bits, so a merely-revisited directory (or one `copystat()`
    touched only) never looks changed. A file's tuple adds size, mtime_ns
    AND the permission bits (review round 1 code-review MEDIUM: `os.chmod`
    is explicitly in `_WRITE_BOTH`'s write-candidate event table, but a
    chmod-only change to a file — same inode, size and mtime — was
    otherwise invisible to both the per-test guard and the AC-7 advisory
    diff; there is no D-204-style false-positive reason to exclude mode
    bits for FILES the way there is for directories), so a same-inode
    rewrite OR a chmod-only change is still caught.

    [!DECISION D-219] owner=impl-agent date=2026-09-29 refs=step-2: catches
    Exception broadly, not just OSError. The AC-9 full-suite run on the
    scratch copy found `tests/test_test_conventions.py::test_no_io_on_either_call_path`
    monkeypatching `os.stat` to always raise `AssertionError` (its own,
    unrelated I/O-boundary test) — session teardown ran this module's
    `snapshot()` afterwards and the exception propagated out of
    `pytest_sessionfinish` into an INTERNAL pytest error. AC-7 requires the
    session-end diff to be advisory ONLY and never affect the run; a single
    hostile-environment stat call must degrade this one path's state to
    "unknown", never crash the session.
    """
    try:
        st = os.lstat(p)
    except Exception:
        return None
    if stat.S_ISDIR(st.st_mode):
        return ("dir", st.st_ino, st.st_dev)
    return ("file", st.st_ino, st.st_dev, st.st_size, st.st_mtime_ns,
           stat.S_IMODE(st.st_mode))


def _normalise_root(root) -> str:
    return os.path.realpath(str(root)).rstrip(os.sep) + os.sep


class Guard:
    """Watches `roots` for the life of one process (or one probe).

    `violations(test_id)` merges in-memory candidates (this process) with
    the report file's lines for that test id (a subprocess relayed through
    `report_path`), and reports every path whose CURRENT state differs from
    its recorded pre-state.
    """

    def __init__(self, roots, report_path: str | None = None, owner: str | None = None):
        self.roots = tuple(_normalise_root(r) for r in roots)
        self.report_path = report_path
        # Review round 1 ext MEDIUM (AC-6): the id of the test that OWNS
        # this process, captured once (by `install_from_env`, from the
        # inherited $PYTEST_CURRENT_TEST, before anything in THIS process
        # could overwrite it) — never re-read. A nested pytest session that
        # does not load this plugin still updates $PYTEST_CURRENT_TEST
        # itself (a core pytest behaviour, independent of any plugin), so a
        # write it performs gets tagged with ITS OWN (inner) test id under
        # the dynamic `current_test_id()` — with no plugin loaded there to
        # ever evaluate that inner id, the outer spawning test would see
        # nothing. Tagging every report line with the STATIC owner too, and
        # matching on EITHER field, lets the outer test still catch it.
        self.owner = owner
        self._pre: dict[tuple[str, str], tuple | None] = {}
        self._consumed: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def _under_roots(self, ap: str) -> bool:
        probe = ap + os.sep
        return any(probe.startswith(r) or ap + os.sep == r for r in self.roots)

    def on_event(self, event: str, args: tuple) -> None:
        candidates = list(_candidate_paths(event, args))
        if not candidates:
            return
        test_id = current_test_id()
        for p in candidates:
            try:
                ap = os.path.realpath(p)
            except Exception:
                continue
            if not self._under_roots(ap):
                continue
            with self._lock:
                is_new = (test_id, ap) not in self._pre
                if is_new:
                    self._pre[(test_id, ap)] = path_state(ap)
                    pre_state = self._pre[(test_id, ap)]
            if is_new and self.report_path:
                self._append_report(test_id, ap, pre_state)

    def _append_report(self, test_id: str, ap: str, pre_state) -> None:
        rec = {
            "test": test_id,
            "owner": self.owner,
            "path": ap,
            "state": list(pre_state) if pre_state is not None else None,
        }
        try:
            with open(self.report_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    def _report_candidates(self, test_id: str):
        # D-219: `violations`/`forget` run for EVERY test's report, not just
        # a test that actually wrote to a guarded root — a test that
        # deliberately breaks os.stat/open for its OWN purposes (e.g.
        # tests/test_test_conventions.py::test_no_io_on_either_call_path)
        # must never see ITS assertion tripped by the guard's own
        # unconditional bookkeeping (AC-6: the guard must never disrupt a
        # test that never wrote anywhere).
        try:
            if not self.report_path or not os.path.exists(self.report_path):
                return
            text = Path(self.report_path).read_text(encoding="utf-8")
        except Exception:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("test") != test_id and rec.get("owner") != test_id:
                continue
            path = rec.get("path")
            if path is None or not self._under_roots(path):
                continue
            if (test_id, path) in self._consumed:
                continue
            state = rec.get("state")
            yield path, (tuple(state) if state is not None else None)

    def violations(self, test_id: str) -> list[str]:
        """D-219: never raises — a hostile-environment test (one that
        monkeypatches os/Path for its own purposes) must never see the
        guard's own bookkeeping turn into an exception ON ITS report."""
        try:
            with self._lock:
                pre = {p: s for (t, p), s in self._pre.items() if t == test_id}
            for path, state in self._report_candidates(test_id):
                pre.setdefault(path, state)
            return sorted(p for p, s in pre.items() if path_state(p) != s)
        except Exception:
            return []

    def forget(self, test_id: str) -> None:
        """Drop this test's in-memory candidates AND mark its report-file
        lines as consumed, so a later evaluation (e.g. a teardown report
        after a call report already failed on the very same on-disk report
        lines) never re-reports the same violation (impl-plan-review F-3).
        D-219: never raises, for the same reason as `violations()`."""
        try:
            for path, _state in list(self._report_candidates(test_id)):
                self._consumed.add((test_id, path))
        except Exception:
            pass
        with self._lock:
            self._pre = {(t, p): s for (t, p), s in self._pre.items() if t != test_id}

    def reconfigure(self, roots, report_path: str | None = None) -> None:
        """Repoint this SAME guard at new roots/report file. Used when a
        process already has a primary guard (installed by the shim before
        pytest even started) and the plugin's `pytest_configure` wants to
        take it over rather than add a second dispatcher target (there is
        one dispatcher and one Guard per process, impl-plan-review F-3)."""
        self.roots = tuple(_normalise_root(r) for r in roots)
        if report_path is not None:
            self.report_path = report_path


class ReadTracker:
    """The read-mode twin of `Guard`, for `no_index_reads` (step-3+)."""

    def __init__(self, roots, log_path: str):
        self.roots = tuple(_normalise_root(r) for r in roots)
        self.log_path = log_path

    def _under_roots(self, ap: str) -> bool:
        probe = ap + os.sep
        return any(probe.startswith(r) or ap + os.sep == r for r in self.roots)

    def on_event(self, event: str, args: tuple) -> None:
        for p in _read_paths(event, args):
            try:
                ap = os.path.realpath(p)
            except Exception:
                continue
            if not self._under_roots(ap):
                continue
            rec = {"test": current_test_id(), "path": ap}
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass


def read_records(log_path) -> list[dict]:
    p = Path(log_path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def default_roots(framework_root, project_root) -> list[str]:
    """The three guarded roots (F-016): the klc repo's own `.klc`, the
    session-start project root's `.klc`, and the unset-fallback
    `framework_root().parent/.klc` — deduplicated (the project root and the
    fallback coincide whenever `PROJECT_ROOT` was never set)."""
    candidates = [
        Path(framework_root) / ".klc",
        Path(project_root) / ".klc",
        Path(framework_root).parent / ".klc",
    ]
    seen: set[str] = set()
    out = []
    for c in candidates:
        key = os.path.realpath(str(c))
        if key not in seen:
            seen.add(key)
            out.append(str(c))
    return out


def snapshot(roots) -> dict[str, tuple | None]:
    """A full-tree snapshot of every path under `roots`, `.git` excluded,
    for the session-end advisory diff. D-219: each root's walk is isolated
    in its own try/except — one root's failure never loses the others, and
    never propagates (AC-7: advisory only, must never affect the run)."""
    state: dict[str, tuple | None] = {}
    for root in roots:
        try:
            root = Path(root)
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d != ".git"]
                if Path(dirpath).name == ".git":
                    continue
                for name in list(dirnames) + list(filenames):
                    p = os.path.join(dirpath, name)
                    state[p] = path_state(p)
        except Exception:
            continue
    return state


def diff_snapshots(before: dict, after: dict) -> list[tuple[str, str]]:
    """Returns (kind, path) tuples, kind in ADDED/REMOVED/MODIFIED, sorted."""
    out = []
    for p in after.keys() - before.keys():
        out.append(("ADDED", p))
    for p in before.keys() - after.keys():
        out.append(("REMOVED", p))
    for p in before.keys() & after.keys():
        if before[p] != after[p]:
            out.append(("MODIFIED", p))
    out.sort(key=lambda t: (t[1], t[0]))
    return out


def track_reads(roots, log_path: str) -> ReadTracker:
    tracker = ReadTracker(roots, log_path)
    _activate(tracker)
    return tracker


# --- the one process-wide dispatcher ---------------------------------------

_ACTIVE: list = []
_ACTIVE_LOCK = threading.Lock()
_HOOK_INSTALLED = False
_DEGRADED = False
_DISPATCHING = threading.local()
_PRIMARY_GUARD: Guard | None = None


def activate(observer) -> None:
    """Adds an EXTRA active observer (a `Guard` or `ReadTracker`) without
    disturbing whatever the process's primary guard already is — the
    dispatcher forwards every event to every active observer, so a test can
    watch its own stand-in root alongside the real session guard."""
    _ensure_hook_installed()
    with _ACTIVE_LOCK:
        _ACTIVE.append(observer)


_activate = activate  # internal alias, used before `activate` existed as public API


def deactivate(observer) -> None:
    with _ACTIVE_LOCK:
        if observer in _ACTIVE:
            _ACTIVE.remove(observer)


def _dispatch(event: str, args: tuple) -> None:
    if getattr(_DISPATCHING, "on", False):
        return
    _DISPATCHING.on = True
    try:
        with _ACTIVE_LOCK:
            observers = list(_ACTIVE)
        for observer in observers:
            try:
                observer.on_event(event, args)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _DISPATCHING.on = False


def _ensure_hook_installed(add_hook=None) -> bool:
    """Installs the ONE process-wide dispatcher, at most once. Returns
    whether an audit hook backs the guard in this process (False means
    degraded: per-test failures never fire, only the session-end diff
    still works, since it is snapshot-based, not hook-based)."""
    global _HOOK_INSTALLED, _DEGRADED
    if _HOOK_INSTALLED:
        return True
    if _DEGRADED:
        return False
    if os.environ.get("KLC_LIVE_GUARD_NO_AUDITHOOK"):
        _DEGRADED = True
        return False
    hook = add_hook if add_hook is not None else sys.addaudithook
    try:
        hook(_dispatch)
    except Exception:
        _DEGRADED = True
        return False
    _HOOK_INSTALLED = True
    return True


def install(roots, report_path: str | None = None, add_hook=None,
           owner: str | None = None) -> Guard | None:
    """Installs (once) the process-wide dispatcher and activates a NEW
    primary `Guard` over `roots`. Returns None (degraded) if the audit hook
    could not be installed AND none is already active — the caller (the
    plugin) still gets a session-end diff via `snapshot`/`diff_snapshots`,
    which never depends on the hook."""
    global _PRIMARY_GUARD
    ok = _ensure_hook_installed(add_hook)
    guard = Guard(roots, report_path, owner=owner)
    if ok:
        _activate(guard)
        _PRIMARY_GUARD = guard
        return guard
    return None


def current_guard() -> Guard | None:
    return _PRIMARY_GUARD


def is_degraded() -> bool:
    return _DEGRADED


def install_from_env(environ=None) -> Guard | None:
    """Called by `sitecustomize.py` (and directly, by the plugin, when it
    finds no primary guard yet installed). Reads the env contract:
    `KLC_LIVE_GUARD_ROOTS`, `KLC_LIVE_GUARD_REPORT`,
    `KLC_LIVE_GUARD_READ_ROOTS`, `KLC_LIVE_GUARD_READ_LOG`,
    `KLC_LIVE_GUARD_NO_AUDITHOOK`."""
    env = environ if environ is not None else os.environ
    # Captured HERE, immediately, before pytest (if this process turns out
    # to run a nested pytest session of its own) can ever overwrite
    # $PYTEST_CURRENT_TEST with its own node ids (review round 1 ext
    # MEDIUM). This is the id of whichever test SPAWNED this process.
    owner = current_test_id() or None

    guard = None
    roots_env = env.get("KLC_LIVE_GUARD_ROOTS")
    if roots_env:
        roots = [r for r in roots_env.split(os.pathsep) if r]
        primary = current_guard()
        if primary is not None:
            primary.reconfigure(roots, env.get("KLC_LIVE_GUARD_REPORT"))
            guard = primary
        else:
            guard = install(roots, env.get("KLC_LIVE_GUARD_REPORT"), owner=owner)

    read_roots_env = env.get("KLC_LIVE_GUARD_READ_ROOTS")
    log_path = env.get("KLC_LIVE_GUARD_READ_LOG")
    if read_roots_env and log_path:
        read_roots = [r for r in read_roots_env.split(os.pathsep) if r]
        track_reads(read_roots, log_path)

    return guard
