#!/usr/bin/env python3
"""index_refresh.py — KLC-107: the verb-side freshness seam.

`refresh_if_stale` is the ONE shared helper `klc intake`, `klc next` and
`klc ack` call before they touch any index artifact or per-ticket state
(spec C-002 / Approach B). It:

  - is a no-op when `.last-run` already equals `HEAD` (AC-10);
  - is suppressible by a flag or `KLC_NO_INDEX_REFRESH=1` (AC-11);
  - refuses to run while another writer holds the index lock — the verb
    is never blocked by index contention, it just continues with
    whatever index it has (D-201, finding F-1's verb-side half);
  - bounds the refresh by a configurable wall-clock budget, and on
    timeout kills the WHOLE process tree it spawned, not just the direct
    child (D-202, finding F-2) — `scripts/update.py` spawns its own
    builder subprocesses with their own multi-minute timeouts, so
    killing only the direct child would leave a grandchild writing
    `.klc/index/` for minutes after the verb has moved on;
  - can never raise (AC-13): every failure mode is caught and reported
    on `out` (default `sys.stderr`), and the verb's exit code is never
    touched by the return value here — callers discard it on purpose.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))
import index_lock as _lock  # noqa: E402
import verify_runner as _verify_runner  # noqa: E402  (KLC-115 D-002: promoted kill/spawn)

_FRAMEWORK_ROOT = _SKILLS.parent.parent
_UPDATE_SCRIPT = _FRAMEWORK_ROOT / "scripts" / "update.py"   # monkeypatchable in tests

DEFAULT_BUDGET_S = 30.0          # a full run measures ~1.9s median here (KLC-121
                                  # F-014, superseding the prior estimate this
                                  # comment carried in from KLC-107's design
                                  # (roughly 2.9x pessimistic); every refresh
                                  # is still a FULL rebuild until KLC-125
                                  # lands the incremental merge
LOCK_WAIT_S = 2.0                # D-201: a verb never blocks on the index lock
ENV_SUPPRESS = "KLC_NO_INDEX_REFRESH"


def suppressed_by_env() -> bool:
    return os.environ.get(ENV_SUPPRESS) == "1"


def budget_seconds() -> float:
    """AC-12: read from settings, project override wins over the framework
    default (spec Q-004). Uses `settings.resolve` directly rather than a
    named accessor — step-6 registers the key with the validator but adds
    no new call site here."""
    if str(_SKILLS) not in sys.path:
        sys.path.insert(0, str(_SKILLS))
    import settings as _settings
    try:
        return float(_settings.resolve(
            "index.refresh_budget_seconds", legacy_file="profile.yml",
            legacy_key="index_refresh_budget_seconds", default=DEFAULT_BUDGET_S))
    except (TypeError, ValueError):
        return DEFAULT_BUDGET_S


def _git_head(root: Path) -> str:
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else ""


def _kill_tree(proc: subprocess.Popen) -> None:
    """AC-12 says the REFRESH is terminated, not merely the process we
    launched. `scripts/update.py` spawns builders with their own 300/600/120s
    timeouts, so killing only the direct child leaves a grandchild writing
    `.klc/index/` for minutes (finding F-2).

    Delegates to `verify_runner.kill_tree` (KLC-115 D-002): the POSIX
    `killpg`/Windows `taskkill` implementation now lives there, promoted
    verbatim, so this module keeps exactly one caller of exactly one
    implementation rather than a second copy free to drift."""
    _verify_runner.kill_tree(proc)


def _spawn(cmd: list[str], env: dict) -> subprocess.Popen:
    """Delegates to `verify_runner.spawn` (KLC-115 D-002), with
    `merge_stderr=False` to keep this module's original two-pipe (separate
    stdout/stderr) capture shape — `refresh_if_stale`'s failure-detail
    reporting reads real stderr text out of the second element of
    `proc.communicate()`."""
    return _verify_runner.spawn(cmd, env=env, merge_stderr=False)


def refresh_if_stale(root, *, suppressed: bool = False, budget_s: float | None = None,
                      out=None) -> dict:
    # `out` defaults to the CURRENT sys.stderr, looked up at call time rather
    # than bound as a mutable default at import time — so a caller using
    # contextlib.redirect_stderr around the verb still captures this output.
    if out is None:
        out = sys.stderr
    result = {"status": "failed", "last": "", "head": "", "elapsed_s": 0.0, "detail": ""}
    try:
        root = Path(root)
        index_dir = root / ".klc" / "index"
        last_file = index_dir / ".last-run"

        if suppressed or suppressed_by_env():
            out.write("[index] refresh suppressed — the index may be behind HEAD\n")
            return {**result, "status": "suppressed"}

        if not last_file.exists():
            out.write("[index] no baseline — run `klc init --scan-only`\n")
            return {**result, "status": "uninitialised"}

        last = last_file.read_text(encoding="utf-8").strip()
        head = _git_head(root)
        result.update(last=last, head=head)
        if not head or last == head:
            return {**result, "status": "fresh"}   # AC-10: no spawn, no lock

        budget = budget_s if budget_s is not None else budget_seconds()
        started = time.monotonic()
        try:
            with _lock.acquire_index_lock(index_dir, wait_s=LOCK_WAIT_S):
                env = {**os.environ, "PROJECT_ROOT": str(root),
                       _lock.ENV_HELD: "1"}   # the child must not re-acquire
                proc = _spawn([sys.executable, str(_UPDATE_SCRIPT)], env)
                try:
                    stdout_text, errtext = proc.communicate(timeout=budget)
                except subprocess.TimeoutExpired:
                    _kill_tree(proc)
                    out.write(f"[index] refresh exceeded the {budget:g}s budget "
                              f"(settings key index.refresh_budget_seconds) — the "
                              f"refresh and every builder it started were stopped; "
                              f"the baseline is unchanged and the next verb retries\n")
                    return {**result, "status": "timeout",
                            "elapsed_s": time.monotonic() - started}
        except _lock.IndexBusy as busy:
            out.write(f"[index] another refresh is in progress (PID {busy.pid}) — "
                      f"skipped; this verb continues\n")
            return {**result, "status": "busy"}

        elapsed = time.monotonic() - started
        if proc.returncode != 0:
            out.write(f"[index] refresh failed in scripts/update.py "
                      f"(exit {proc.returncode}); the verb continues\n")
            return {**result, "status": "failed", "elapsed_s": elapsed,
                    "detail": (errtext or "").strip()[-500:]}
        out.write(f"[index] refreshed {last[:8]}..{head[:8]} in {elapsed:.1f}s\n")
        return {**result, "status": "refreshed", "elapsed_s": elapsed}
    except BaseException as exc:             # AC-13: nothing escapes, ever
        out.write(f"[index] refresh helper failed ({type(exc).__name__}: {exc}); "
                  f"the verb continues\n")
        return {**result, "detail": str(exc)}
