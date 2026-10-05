"""step_state.py — KLC-174: per-step build state in `build/steps.json`.

Role: the single place where a plan step's VERIFY command is executed
(`record_verify`) and the single reader of the result (`read`, `derive`,
`check_build`). Nothing else may spawn a VERIFY.

Why: build ack used to replay shell commands pasted into build-log.md. Now the
agent commits, then runs `klc step verify <KEY> N` once; the result is stored
and ack only READS it.

Unusual on purpose: steps.json is untrusted input. Only the `verify` object is
read from the file, and even that is re-validated (command must equal the plan's
VERIFY, exit 0, run on a clean tree at a HEAD that contains the green commit, with
a `ran_at` that is not in the future). Commits, state and TDD order are
recomputed from git on every `derive`. A hand-written steps.json that claims green
is trusted only up to those derived checks: it proves a verify was RECORDED, not
that it ran (a deliberate trust shift from the removed Evidence replay). A stored command is never executed:
`record_verify` re-parses the command from impl-plan.md and runs it through
`command_allowlist`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import command_allowlist  # noqa: E402
import impl_plan_check  # noqa: E402
import settings  # noqa: E402
import tdd_order  # noqa: E402
import verify_runner  # noqa: E402
from _paths import klc_ticket_dir, project_root  # noqa: E402

_SUMMARY_MAX = 200
_VERIFY_KEYS = ("command", "exit_code", "summary_line", "ran_at", "runner", "head", "dirty")
_FUTURE_SKEW_S = 120      # clock skew tolerated for a recorded ran_at


# --------------------------------------------------------------- small helpers

def _root(repo) -> Path:
    return Path(repo) if repo else project_root()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _steps_file(ticket: str) -> Path:
    return klc_ticket_dir(ticket) / "build" / "steps.json"


def _plan_text(ticket: str) -> str:
    try:
        return (klc_ticket_dir(ticket) / "impl-plan.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def _clean_command(raw: str) -> str:
    # Copied from step_verify._clean_command: that module is deleted later in KLC-174.
    c = (raw or "").strip()
    if len(c) >= 2 and c.startswith("`") and c.endswith("`"):
        c = c[1:-1].strip()
    return c


def _plan_command(step: dict) -> str:
    fields = impl_plan_check.extract_step_fields(step["body"])
    return _clean_command(fields.get("verify", ""))


def _summary(output: str) -> str:
    lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
    return lines[-1][:_SUMMARY_MAX] if lines else ""


def _step_no(step: dict) -> int:
    return int(step["id"].split("-")[1])


# ------------------------------------------------------------------ the file

def read(ticket: str) -> dict:
    """`{step:int -> {"verify": {...}, "review": {...}?}}` from steps.json; `{}` when the file is
    missing, corrupt or not the expected shape. Never raises, never trusted."""
    try:
        data = json.loads(_steps_file(ticket).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, dict):
        return {}
    out: dict[int, dict] = {}
    for key, rec in steps.items():
        try:
            n = int(key)
        except (TypeError, ValueError):
            continue
        verify = rec.get("verify") if isinstance(rec, dict) else None
        review = rec.get("review") if isinstance(rec, dict) else None
        if isinstance(verify, dict) or isinstance(review, dict):
            out[n] = {}
            if isinstance(verify, dict):
                out[n]["verify"] = verify
            if isinstance(review, dict):
                out[n]["review"] = review
    return out


def _write_atomic(ticket: str, step: int, **fields) -> None:
    """Merge *fields* (`verify=`, `review=`; a None value deletes the key) into the
    step's record and rewrite the file atomically."""
    path = _steps_file(ticket)
    path.parent.mkdir(parents=True, exist_ok=True)
    steps = {str(n): rec for n, rec in read(ticket).items()}
    rec = dict(steps.get(str(step), {}))
    for key, value in fields.items():
        if value is None:
            rec.pop(key, None)
        else:
            rec[key] = value
    steps[str(step)] = {"step": step, **rec}
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps({"steps": steps}, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ recording

def _git(args, repo, timeout=30):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=str(_root(repo)), timeout=timeout)


def _head(repo) -> str | None:
    try:
        r = _git(["rev-parse", "HEAD"], repo)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _dirty(repo) -> bool | None:
    """True when a TRACKED file differs from HEAD (`.klc/` ignored); None when git
    cannot say."""
    try:
        r = _git(["status", "--porcelain", "--untracked-files=no"], repo)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    paths = [ln[3:].split(" -> ")[-1].strip().strip('"') for ln in r.stdout.splitlines()
             if ln.strip()]
    return any(not p.startswith(".klc/") for p in paths)


def record_verify(ticket, step, *, runner="agent", repo=None) -> dict:
    """Run the plan's VERIFY for *step* through the allowlist and store the result.

    A refused command is stored as `unverified: command-not-allowed: ...` with
    `exit_code` None and is never executed. Raises KeyError for an unknown step."""
    plan = {s["id"]: s for s in impl_plan_check.parse_impl_plan_steps(_plan_text(ticket))}
    if f"step-{step}" not in plan:
        raise KeyError(f"{ticket}: impl-plan.md has no step-{step}")
    command = _plan_command(plan[f"step-{step}"])
    extra = settings.resolve("verify.allowed_programs", default=[])
    ok, why = command_allowlist.check(command, extra if isinstance(extra, list) else [])
    head = _head(repo)
    dirty = _dirty(repo)
    if not ok:
        verify = {"command": command, "exit_code": None,
                  "summary_line": f"unverified: {why}", "ran_at": _now(), "runner": runner,
                  "head": head, "dirty": dirty}
    else:
        try:
            v = verify_runner.run(command, budget_s=settings.verify_step_budget(),
                                  cwd=str(_root(repo)))
        except (ValueError, OSError):   # e.g. a NUL byte in the command
            v = None
        if v is None:
            code, summary = None, "unverified: command-not-runnable"
        else:
            code = v.exit_code
            summary = (f"unverified: {v.advisory()}" if v.state == verify_runner.UNVERIFIED
                       else _summary(v.output))
        after = _dirty(repo)
        verify = {"command": command, "exit_code": code, "summary_line": summary,
                  "ran_at": _now(), "runner": runner, "head": head,
                  "dirty": None if dirty is None or after is None else (dirty or after)}
    _write_atomic(ticket, step, verify=verify)
    return verify


def mark_review(ticket, step, state, *, round=1, repo=None) -> dict:
    """Record the per-step review outcome (`"blocked"` | `"passed"`) in steps.json.

    Written only by the orchestrator. The marker remembers the step's latest
    commit, so a NEW commit makes it stale (see `derive`). Never raises on I/O."""
    if state not in ("blocked", "passed"):
        raise ValueError(f"review state must be blocked|passed, got {state!r}")
    commits = tdd_order.step_commits(ticket, step, Path(repo) if repo else None)
    review = {"state": state, "at": _now(), "round": round,
              "commit": commits[-1]["sha"] if commits else None}
    try:
        _write_atomic(ticket, step, review=review)
    except OSError:
        pass
    return review


def _review_blocks(review, green) -> bool:
    """True when a `blocked` marker still applies to the step's latest commit."""
    if not isinstance(review, dict) or review.get("state") != "blocked":
        return False
    return bool(green) and review.get("commit") == green


# ------------------------------------------------------------------- deriving

def _commit_epoch(sha: str, repo) -> int | None:
    try:
        r = subprocess.run(["git", "show", "-s", "--format=%ct", sha], capture_output=True,
                           text=True, cwd=str(_root(repo)), timeout=30)
        return int(r.stdout.strip()) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _is_ancestor(green: str, head: str, repo) -> bool:
    try:
        return _git(["merge-base", "--is-ancestor", green, head], repo).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _verify_problem(verify, plan_command: str, green: str, repo) -> str:
    """"" when the stored verify is valid for this step, else the reason.

    Primary check: the verify ran on a clean tree at a HEAD that contains the green
    commit (so a later fix commit, or a rebase that rewrites it, invalidates it).
    The `ran_at` comparison is a secondary sanity check, and a `ran_at` in the
    future never goes stale, so it is refused."""
    if not isinstance(verify, dict):
        return "no recorded verify — run `klc step verify`"
    if verify.get("command") != plan_command:
        return "recorded verify command differs from the plan VERIFY"
    code = verify.get("exit_code")
    if isinstance(code, bool) or not isinstance(code, int):
        return f"verify did not run to completion ({verify.get('summary_line') or 'no exit code'})"
    if code != 0:
        return f"verify failed (exit {code})"
    try:
        ran = datetime.strptime(verify.get("ran_at"), "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return "recorded verify has no valid ran_at"
    if ran > time.time() + _FUTURE_SKEW_S:
        return "unverified: ran_at in the future"
    head = verify.get("head")
    if not isinstance(head, str) or not head:
        return "recorded verify has no head — re-run `klc step verify`"
    if verify.get("dirty") is not False:
        return "recorded verify ran on a dirty working tree — commit, then re-run `klc step verify`"
    if not _is_ancestor(green, head, repo):
        return "recorded verify is older than the green commit — re-run `klc step verify`"
    committed = _commit_epoch(green, repo)
    if committed is None:
        return "green commit time unreadable from git"
    if ran + _FUTURE_SKEW_S < committed:   # same skew tolerance as the future bound
        return "recorded verify is older than the green commit — re-run `klc step verify`"
    return ""


def derive(ticket, repo=None, persist: bool = True) -> list[dict]:
    """One record per impl-plan step, recomputed from git and the plan.

    `{step, state, red_commit, green_commit, verify, addresses, reason, verify_stale}`;
    state is pending|red|green|blocked. `verify_stale` is true only when the step is
    non-green solely because its verify predates the latest commit. `verify` and the
    review marker come from the file (unvalidated); a blocked marker holds until a
    new commit lands, then it is stale and removed from the file — only when
    *persist* is true; `persist=False` (the read-only probes) never writes."""
    repo_p = Path(repo) if repo else None
    stored = read(ticket)
    out = []
    for s in impl_plan_check.parse_impl_plan_steps(_plan_text(ticket)):
        n = _step_no(s)
        body = impl_plan_check._ANY_FENCE_RE.sub("", s["body"])
        red_na = impl_plan_check._red_not_applicable(body)
        commits = tdd_order.step_commits(ticket, n, repo_p)
        kinds = [tdd_order.classify(c["sha"], repo_p) for c in commits]
        red = next((c["sha"] for c, k in zip(commits, kinds) if k == "test"), None)
        green = commits[-1]["sha"] if commits else None
        verify = stored.get(n, {}).get("verify")
        review = stored.get(n, {}).get("review")
        reason, stale = "", False
        if not commits:
            state, reason = "pending", "no commits for this step yet"
        elif not red_na and (ok_reason := tdd_order.verify_step(ticket, n, repo_p))[0] is False:
            state, reason = "blocked", f"TDD order: {ok_reason[1]}"
        elif not red_na and all(k == "test" for k in kinds):
            state, reason = "red", "only test commits so far"
        elif _review_blocks(review, green):
            state, reason = "blocked", "per-step review blocked — commit a fix, then re-run"
        else:
            if persist and isinstance(review, dict) and review.get("state") == "blocked":
                _clear_review(ticket, n)  # a new commit made the marker stale
            reason = _verify_problem(verify, _plan_command(s), green, repo)
            stale = reason.startswith("recorded verify is older")
            state = "blocked" if reason else "green"
        out.append({"step": n, "state": state, "red_commit": red, "green_commit": green,
                    "verify": verify, "addresses": s["addresses"], "reason": reason,
                    "verify_stale": stale})
    return out


def _clear_review(ticket: str, step: int) -> None:
    try:
        _write_atomic(ticket, step, review=None)
    except OSError:
        pass


def check_build(ticket, repo=None, persist: bool = True) -> tuple[bool, str]:
    """`(True, "")` when every plan step is green, else the first one-line reason
    naming the step. An empty plan is not green."""
    recs = derive(ticket, repo, persist=persist)
    if not recs:
        return False, "impl-plan.md has no steps"
    for rec in recs:
        if rec["state"] != "green":
            return False, f"step-{rec['step']}: {rec['state']} — {rec['reason']}"
    return True, ""
