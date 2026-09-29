"""KLC-136 — the pytest plugin half of the live-`.klc` guard.

Registered by `tests/conftest.py` under the plugin name
`klc_live_guard_plugin` (so `-p no:klc_live_guard_plugin` switches it off for
a whole run), or loaded directly by an inner pytest session via
`-p klc_live_guard_plugin` with this directory on `PYTHONPATH`.

- `pytest_configure` resolves the three guarded roots (`KLC_LIVE_GUARD_ROOTS`
  if the environment already names them — an inner session — else
  `klc_live_guard.default_roots` from the session-start paths), creates a
  FRESH report file in its own `tempfile.mkdtemp()` (never reusing one it
  might have inherited), exports the env contract so any subprocess this
  session launches inherits it, and either installs the core (nothing
  active yet in this process) or reconfigures the guard the subprocess shim
  already installed (an inner session) — there is one dispatcher and one
  `Guard` per process (impl-plan-review F-3).
- `pytest_runtest_makereport` (hookwrapper) turns a `call` or `teardown`
  report with violations into a failure naming the test and every violating
  path, and tells the guard to forget this test's candidates either way, so
  a teardown evaluation never re-reports a violation the call report
  already failed on.
- The session-end snapshot diff (`pytest_sessionstart`/`pytest_sessionfinish`)
  is purely advisory (B1, Q-002 / D-215): `pytest_terminal_summary` prints it
  as plain terminal lines and never touches the exit status, so a concurrent
  agent's write to a guarded root (F-014) cannot fail a run through this
  path — only the per-test guard above can fail a run, and only for the
  test that did the writing.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_GUARD_DIR = os.path.dirname(os.path.abspath(__file__))
if _GUARD_DIR not in sys.path:
    sys.path.insert(0, _GUARD_DIR)

import klc_live_guard as klg  # noqa: E402

_REPO_ROOT = Path(_GUARD_DIR).resolve().parent.parent.parent
_SKILLS_PATH = str(_REPO_ROOT / "core" / "skills")

# Per-session state, keyed by the pytest Config object (a module-level dict
# rather than an attribute on `config` because a plain module-scope global
# is enough — pytest never runs two sessions in one process at once — but
# keying by config avoids any doubt if it ever did).
_STATE: dict = {}


def _resolve_roots() -> list[str]:
    roots_env = os.environ.get("KLC_LIVE_GUARD_ROOTS")
    if roots_env:
        return [r for r in roots_env.split(os.pathsep) if r]
    if _SKILLS_PATH not in sys.path:
        sys.path.insert(0, _SKILLS_PATH)
    import _paths  # type: ignore
    return klg.default_roots(_paths.framework_root(), _paths.project_root())


def resolved_roots(config: pytest.Config) -> list[str] | None:
    """The roots THIS session's guard is actually watching (test-facing
    accessor, e.g. `test_guard_watches_all_three_roots`)."""
    state = _STATE.get(config)
    return None if state is None else state["roots"]


def pytest_configure(config: pytest.Config) -> None:
    roots = _resolve_roots()

    report_dir = tempfile.mkdtemp(prefix="klc_live_guard_")
    report_path = os.path.join(report_dir, "report.jsonl")

    os.environ["KLC_LIVE_GUARD_ROOTS"] = os.pathsep.join(roots)
    os.environ["KLC_LIVE_GUARD_REPORT"] = report_path
    existing_pp = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if _GUARD_DIR not in existing_pp:
        os.environ["PYTHONPATH"] = os.pathsep.join([_GUARD_DIR] + existing_pp)

    primary = klg.current_guard()
    degraded = False
    if primary is not None:
        primary.reconfigure(roots, report_path)
        guard = primary
    else:
        guard = klg.install(roots, report_path)
        degraded = guard is None

    _STATE[config] = {
        "roots": roots,
        "report_path": report_path,
        "guard": guard,
        "degraded": degraded,
        "degrade_announced": False,
        "before": None,
        "after": None,
    }


def pytest_sessionstart(session: pytest.Session) -> None:
    state = _STATE.get(session.config)
    if state is None:
        return
    try:
        state["before"] = klg.snapshot(state["roots"])
    except Exception:
        state["before"] = None


def pytest_sessionfinish(session: pytest.Session) -> None:
    """D-219: the advisory snapshot must never affect the run (AC-7) — even
    though `klg.snapshot` already isolates each root's own failure, this
    call is wrapped too so a defect in the plugin's OWN bookkeeping can
    never turn into an internal pytest error at session teardown."""
    state = _STATE.get(session.config)
    if state is None:
        return
    try:
        state["after"] = klg.snapshot(state["roots"])
    except Exception:
        state["after"] = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    outcome = yield
    rep = outcome.get_result()
    state = _STATE.get(item.config)
    guard = state["guard"] if state else None
    if guard is None or rep.when not in ("call", "teardown"):
        return
    paths = guard.violations(item.nodeid)
    guard.forget(item.nodeid)
    if paths:
        rep.outcome = "failed"
        lines = [f"live .klc write by {item.nodeid}: {p}" for p in paths]
        if rep.longrepr and rep.when == "call":
            lines.append(str(rep.longrepr))
        rep.longrepr = "\n".join(lines)


def pytest_terminal_summary(terminalreporter, exitstatus, config: pytest.Config) -> None:
    """D-219: the whole body is best-effort — a terminal-summary hook must
    never itself become the reason a run reports an internal error."""
    try:
        state = _STATE.get(config)
        if state is None:
            return
        if state["degraded"] and not state["degrade_announced"]:
            state["degrade_announced"] = True
            terminalreporter.write_line(
                "klc live guard: audit hooks unavailable; per-test guard off, "
                "session diff only"
            )
        before, after = state.get("before"), state.get("after")
        if before is None or after is None:
            return
        for kind, path in klg.diff_snapshots(before, after):
            terminalreporter.write_line(
                f"live .klc change during session (advisory): {kind} {path}"
            )
    except Exception:
        pass
