#!/usr/bin/env python3
"""verify_runner.py — KLC-115: one bounded command executor, shared by every
verification site in the framework, returning `pass | fail | unverified`.

The addendum to GAP-562 (`spec.md`'s Problem/Context) records three sites that
each invented their own idea of "verified": the Evidence gate accepted a
section heading with no execution at all, the impl-plan step VERIFY was never
re-run, and `ac_test_coverage` ran every AC node-id in one batched pytest with
a hardcoded 300-second timeout whose except-arm rendered a timeout as "not
passing" for every node. All three defects are one defect: there was no name
for the state between pass and fail. This module gives that state a name —
`unverified`, always carrying a reason — and gives bounded execution exactly
one implementation, so a fix here fixes all three call sites at once.

AC-19 is structural, not a promise: `run()` decides `pass` vs `fail` from the
subprocess exit status ALONE and never inspects `stdout`/`stderr` to do so, so
a command's language, test framework or output shape is invisible to this
layer. A consumer that is allowed to know a specific test runner (only
`ac_test_coverage`, per spec C-007) attributes its own per-node outcomes from
`Verdict.output` — this module hands it the captured stream and stays out of
that business.

`kill_tree` and `spawn` are promoted here from `core/skills/index_refresh.py`
(design D-002): `index_refresh` already implements the POSIX `killpg`
escalation and the Windows `taskkill` branch, once, correctly, and this ticket
does not want a second copy that could drift out of step. The two
`index_refresh` private names become one-line delegations; `index_refresh`
keeps working byte-for-byte from every caller's side.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass

# --- the three states and the closed reason vocabulary ----------------------

PASSED, FAILED, UNVERIFIED = "pass", "fail", "unverified"

# A closed set (AC-7's "distinct state... together with its reason"): every
# consumer of `Verdict.reason` may safely render any member without an
# unbounded string escaping into an advisory. `SLOW` / `SKIPPED` / `UNCOLLECTED`
# / `ARM_BUDGET_EXHAUSTED` are consumer-attributed reasons (ac_test_coverage,
# evidence_gate, step_verify each attribute their own on top of what the
# runner itself ever returns, which is only BUDGET_EXCEEDED or LAUNCH_ERROR).
BUDGET_EXCEEDED = "budget-exceeded"
LAUNCH_ERROR = "launch-error"
SLOW = "slow"
RUNNER_UNAVAILABLE = "runner-unavailable"
NOT_RUN = "not-run"
SKIPPED = "skipped"
UNCOLLECTED = "uncollected"
ARM_BUDGET_EXHAUSTED = "arm-budget-exhausted"

REASONS = frozenset({
    BUDGET_EXCEEDED, LAUNCH_ERROR, SLOW, RUNNER_UNAVAILABLE, NOT_RUN,
    SKIPPED, UNCOLLECTED, ARM_BUDGET_EXHAUSTED,
})

MAX_OUTPUT = 20000   # characters — AC-5's edge case: bound one command's captured output


@dataclass(frozen=True)
class Verdict:
    state: str          # PASSED | FAILED | UNVERIFIED
    reason: str = ""    # a REASONS token; "" on PASSED / FAILED
    detail: str = ""    # human sentence naming the budget/error
    elapsed: float = 0.0
    output: str = ""
    exit_code: int | None = None

    def advisory(self) -> str:
        """`"<reason>: <detail>"` when unverified, else the bare state. KLC-117
        lifts `(reason, detail)` verbatim into a structured advisory record; this
        is the human-readable fallback for a plain-string caller (a CLI, a log)."""
        return f"{self.reason}: {self.detail}" if self.reason else self.state


def spawn(cmd, *, cwd=None, env=None, shell=False, merge_stderr=True):
    """Launch *cmd* as the leader of its own process group/job, so `kill_tree`
    can terminate the whole tree it spawns, not just the direct child.

    `shell=True` keeps an opaque Evidence/VERIFY command opaque — it is handed
    to the platform shell exactly as written, with no parsing on this side.
    `merge_stderr` defaults to True (`run()` wants one combined stream for
    `Verdict.output`); the `index_refresh` delegating alias passes
    `merge_stderr=False` to keep its original two-pipe (separate stdout/stderr)
    capture shape, which `refresh_if_stale`'s error-detail reporting depends on.
    """
    kw: dict = {}
    if os.name == "posix":
        kw["start_new_session"] = True      # child leads its own process group
    else:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    stderr = subprocess.STDOUT if merge_stderr else subprocess.PIPE
    return subprocess.Popen(cmd, cwd=cwd, env=env, shell=shell,
                            stdout=subprocess.PIPE, stderr=stderr,
                            text=True, **kw)


def kill_tree(proc: subprocess.Popen) -> None:
    """Terminate the WHOLE process tree *proc* leads, not merely *proc* itself
    (promoted verbatim from `index_refresh._kill_tree`, F-109): POSIX escalates
    `SIGTERM` to `SIGKILL` across the process group; Windows walks the tree via
    `taskkill /T`. Never raises — every failure mode falls back to killing just
    the direct child."""
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
    else:                                   # Windows: /T walks the tree
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run(command, *, budget_s, cwd=None, env=None, max_output=MAX_OUTPUT) -> Verdict:
    """Execute an OPAQUE *command* (a shell string or an argv list) under a
    wall-clock *budget_s*. Exit status alone decides pass/fail (AC-19) — this
    layer parses NO output. A launch failure (`OSError`, e.g. `ENOENT`) and a
    budget overrun both return `UNVERIFIED` with a named reason: neither is
    ever reported as `FAILED`, which is exactly the collapse this ticket
    exists to undo (AC-7).
    """
    started = time.monotonic()
    try:
        proc = spawn(command, cwd=cwd, env=env, shell=isinstance(command, str))
    except OSError as exc:
        return Verdict(UNVERIFIED, LAUNCH_ERROR,
                       f"could not launch the command ({type(exc).__name__}: {exc})",
                       time.monotonic() - started)
    try:
        out, _ = proc.communicate(timeout=budget_s)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        elapsed = time.monotonic() - started
        return Verdict(UNVERIFIED, BUDGET_EXCEEDED,
                       f"{elapsed:.0f}s > {budget_s:g}s budget", elapsed)
    out = (out or "")[:max_output]
    state = PASSED if proc.returncode == 0 else FAILED
    return Verdict(state, "", "", time.monotonic() - started, out, proc.returncode)


def run_cached(cache, key, command, *, budget_s, cwd=None, env=None,
               max_output=MAX_OUTPUT) -> Verdict:
    """KLC-114 step-12 (review round 1, HIGH; AC-1/AC-11/C-005): identical to
    `run`, except a shared *cache* dict is consulted first under *key* — a
    per-ack Verdict cache lets two independent verification arms
    (`step_verify.check_steps`, `step_ledger.judge_step`) that both need the
    SAME step's SAME command executed at most once per `can_complete_build`
    call, rather than once per arm. `cache=None` (the default for every
    caller that does not opt in) disables caching entirely and behaves
    EXACTLY like `run` — additive, backward compatible."""
    if cache is not None and key in cache:
        return cache[key]
    v = run(command, budget_s=budget_s, cwd=cwd, env=env, max_output=max_output)
    if cache is not None:
        cache[key] = v
    return v
