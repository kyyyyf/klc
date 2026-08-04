#!/usr/bin/env python3
"""drift_check.py — report-only reconciliation of built code vs impl-plan & spec.

KLC-096 (drift-check epic root, D-01). At the integrate phase this produces a
READ-ONLY drift report reconciling the actually-built change against the ticket's
impl-plan and spec. It ships the two high-confidence arrows only:

  - scope-drift        — changed files/modules the plan never declared
                         (reuses scope_delta.compare).
  - step-without-commit — an impl-plan step whose step-key has no matching commit
                         (reuses parse_impl_plan_steps + tdd_order.step_commits),
                         exempting steps legitimately marked `RED: not applicable`.

The precise AC<->code arrow is deferred to the D-02 bridge (KLC-097); the AC<->test
arrow is owned by V-02 (KLC-095) and is deliberately NOT re-derived here (AC-5).

Structural safety invariant (C-003): report-only and degrade-not-fail. compare()
never raises to its caller and never mutates phase state; any missing/unreadable
input degrades to a recorded `skipped` reason on that section, never an exception
and never a false drift. `skipped is None` means the detector RAN (even if it found
nothing) — an empty section is not the same as a skipped one.

CLI:
    python core/skills/drift_check.py --ticket KLC-096 [--repo PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Package-safe path setup (mirrors testplan_review.py): make both the project root
# and this skills dir importable so bare sibling imports resolve under script AND
# package invocation.
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.shared.paths import klc_ticket_dir  # noqa: E402
from scope_delta import compare as _scope_compare  # noqa: E402
from impl_plan_check import (  # noqa: E402
    parse_impl_plan_steps,
    _red_not_applicable,
    _ANY_FENCE_RE,
)
from tdd_order import step_commits  # noqa: E402


def _scope_drift_section(ticket: str) -> dict:
    """Build the scope_drift section from scope_delta.compare. `drifted_modules` is
    the unplanned MODULE set (`drift`), NOT `expansion` — `expansion` is a superset
    that already folds in the orphan file paths (scope_delta.py: `expansion =
    drift | unknown_files`), so using it would double-list every orphan as a module.
    `orphan_files` is the separate `unknown_files`. `skipped` carries scope_delta's
    skip reason verbatim, or None when it ran (even with no drift)."""
    sd = _scope_compare(ticket)
    return {
        "drifted_modules": list(sd.get("drift") or []),
        "orphan_files": list(sd.get("unknown_files") or []),
        "skipped": sd.get("skipped"),
    }


def _git_available(repo: Path | str | None) -> bool:
    """True iff *repo* (or cwd when None) is inside a git work tree. Probing git
    EXPLICITLY (F-1) is required: tdd_order.step_commits swallows every git error
    and returns [], so 'git unavailable' is otherwise indistinguishable from 'git
    ran, no commit' — which would falsely flag every step on a broken git."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(repo) if repo else None,
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _steps_section(ticket: str, plan_text: str | None, repo: Path | str | None) -> dict:
    """Build the step_without_commit section. An ABSENT impl-plan (plan_text is
    None) is `skipped` — distinct from a present-but-empty plan (0 steps), which
    yields an empty section with `skipped is None` (empty != skipped, F-1). Probes
    git availability next: when git is unavailable the section is `skipped` and
    nothing is flagged (never inferred from an empty step_commits, F-1). Otherwise
    a step is `flagged` when its step-key has no matching commit and it is not
    marked `RED: not applicable` (checked on the FENCE-STRIPPED body, F-3);
    commitless RED-not-applicable steps are recorded in `exempt`, never flagged."""
    if plan_text is None:
        return {"flagged": [], "exempt": [], "skipped": "impl-plan.md not found"}
    if not _git_available(repo):
        return {"flagged": [], "exempt": [], "skipped": "git unavailable"}
    flagged: list[str] = []
    exempt: list[str] = []
    for s in parse_impl_plan_steps(plan_text):
        n = int(s["id"].split("-")[1])
        body = _ANY_FENCE_RE.sub("", s["body"])  # strip fences before RED check
        has_commit = bool(step_commits(ticket, n, repo))
        if _red_not_applicable(body):
            if not has_commit:
                exempt.append(s["id"])
            continue
        if not has_commit:
            flagged.append(s["id"])
    return {"flagged": flagged, "exempt": exempt, "skipped": None}


def _safe(fn, *, default: dict) -> dict:
    """Run *fn*, converting ANY exception into a recorded `skipped` reason on a copy
    of *default*. This is the per-section leg of the C-003 degrade-not-fail
    invariant: a broken brick degrades that section to a skip, never propagates."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — report-only: never propagate
        d = dict(default)
        d["skipped"] = f"{type(exc).__name__}: {exc}"
        return d


def compare(ticket: str, *, repo: Path | str | None = None) -> dict:
    """Assemble the (report-only) drift report for *ticket*. Never raises (C-003):
    each section degrades to a `skipped` reason on any error, and compare() itself
    performs no phase mutation — it only computes and returns a dict."""
    scope = _safe(
        lambda: _scope_drift_section(ticket),
        default={"drifted_modules": [], "orphan_files": [], "skipped": None},
    )
    steps = _safe(
        lambda: _steps_from_plan(ticket, repo),
        default={"flagged": [], "exempt": [], "skipped": None},
    )
    return {"ticket": ticket, "scope_drift": scope, "step_without_commit": steps}


def _steps_from_plan(ticket: str, repo: Path | str | None) -> dict:
    """Read the impl-plan and build the step section. Reading is INSIDE the caller's
    `_safe`, so a present-but-unreadable impl-plan (e.g. a decode/permission error)
    surfaces its REAL exception text as the skip-reason — distinct from an absent
    file, which _read_impl_plan reports as None → 'impl-plan.md not found'."""
    return _steps_section(ticket, _read_impl_plan(ticket), repo)


def _read_impl_plan(ticket: str) -> str | None:
    """Read the ticket's impl-plan.md text. Returns None when the file is ABSENT
    (→ a skipped step section) and "" only for a present-but-empty file (→ an
    empty, non-skipped section). A present-but-unreadable file RAISES (caught by
    the caller's _safe, which records the real reason) rather than masquerading as
    absent. The three cases must stay distinct (F-1 / review LOW-1)."""
    path = _read_impl_plan_path(ticket)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _read_impl_plan_path(ticket: str) -> Path:
    """Location of the ticket's impl-plan.md (via the shared, $PROJECT_ROOT-aware
    path helper — not the framework checkout, so multi-project installs resolve the
    correct .klc tree; codex P1)."""
    return klc_ticket_dir(ticket) / "impl-plan.md"


def _report_path(ticket: str) -> Path:
    """Location of the ticket's drift-report.json (shared $PROJECT_ROOT-aware helper)."""
    return klc_ticket_dir(ticket) / "drift-report.json"


def _summary(rep: dict) -> str:
    """One-line human summary that NAMES the drifted modules / orphan files /
    flagged step-keys / skip-reasons (F-2) — not a constant placeholder."""
    sd = rep.get("scope_drift", {}) or {}
    st = rep.get("step_without_commit", {}) or {}
    parts = [f"drift-check {rep.get('ticket', '?')}:"]

    if sd.get("skipped"):
        parts.append(f"scope-drift skipped ({sd['skipped']});")
    else:
        mods = sd.get("drifted_modules") or []
        orph = sd.get("orphan_files") or []
        if mods or orph:
            bits = []
            if mods:
                bits.append(f"{len(mods)} drifted module(s): {', '.join(mods)}")
            if orph:
                bits.append(f"{len(orph)} orphan file(s): {', '.join(orph)}")
            parts.append("; ".join(bits) + ";")
        else:
            parts.append("no scope drift;")

    if st.get("skipped"):
        parts.append(f"step-commit check skipped ({st['skipped']}).")
    else:
        flagged = st.get("flagged") or []
        exempt = st.get("exempt") or []
        if flagged:
            parts.append(f"{len(flagged)} step(s) without a commit: {', '.join(flagged)}.")
        else:
            parts.append("all steps have commits.")
        if exempt:
            parts.append(f"exempt (RED-not-applicable): {', '.join(exempt)}.")

    return " ".join(parts)


def write_report(ticket: str, *, repo: Path | str | None = None) -> dict:
    """Compute the drift report, attach its summary, and write drift-report.json to
    the ticket dir. Report-only: the write is best-effort and never raises to the
    caller (a failed write is recorded, the report dict is still returned)."""
    rep = compare(ticket, repo=repo)
    rep["summary"] = _summary(rep)
    try:
        path = _report_path(ticket)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — report-only: never propagate
        rep["write_error"] = f"{type(exc).__name__}: {exc}"
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="drift-check report-only core (KLC-096)")
    ap.add_argument("--ticket", required=True, help="Ticket key, e.g. KLC-096")
    ap.add_argument(
        "--repo", default=None,
        help="Repo path for the git probe / step-commit check ONLY (default: cwd). "
             "Scope-drift always reconciles against the $PROJECT_ROOT repo.",
    )
    args = ap.parse_args(argv)
    rep = write_report(args.ticket, repo=args.repo)
    print(rep["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
