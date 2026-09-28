#!/usr/bin/env python3
"""step_verify.py — KLC-115: re-execute each impl-plan step's `VERIFY:`
command at build ack and compare the outcome with that step's `Expected:`
field, isolating only the outcome TOKEN before comparing (D-202/F-2).

`impl_plan_check.extract_step_fields` returns a step's `Expected:` field as
the raw captured text, backticks and prose intact (F-105), so comparing the
WHOLE field against terse pytest output would false-block on every real plan
this project has written — the defect the independent review caught (F-2).
`expected_token` isolates the closed-vocabulary outcome token (a count
followed by one of `passed`/`failed`/`skipped`/`xfailed`/`xpassed`/`error(s)`/
`deselected`/`warning(s)`, optionally chained through commas) and that token
alone is what must appear in the re-run's captured output.
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root_dir = _file_dir.parent.parent
for _p in (str(_project_root_dir), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import settings  # noqa: E402
import verify_runner  # noqa: E402
import impl_plan_check  # noqa: E402
from spec_selfreview import PLACEHOLDER_TOKENS  # noqa: E402

BLOCK, SURFACE = "block", "surface"

# D-202: a CLOSED outcome vocabulary. A generic "count followed by a word"
# rule would lift "2 parser tests" out of a real Expected field and demand it
# verbatim in the output.
_WORD = r"(?:passed|failed|skipped|xfailed|xpassed|errors?|deselected|warnings?)"
_TOKEN = re.compile(rf"\d+\s+{_WORD}(?:\s*,\s*\d+\s+{_WORD})*", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join((text or "").replace("`", " ").split()).lower()


def expected_token(expected: str) -> str:
    """Isolate the outcome token from a step's raw `Expected:` field (F-2/D-202).

    Returns "" when the field is prose, which the caller surfaces as
    `expected-unmatchable` rather than blocking."""
    m = _TOKEN.search(_norm(expected))
    return m.group(0) if m else ""


def _token_in_output(token: str, output: str) -> bool:
    """`4 passed` must NOT match inside `24 passed`, so anchor the leading digit."""
    return bool(re.search(r"(?<!\d)" + re.escape(token), _norm(output)))


def _clean_command(raw: str) -> str:
    c = (raw or "").strip()
    if len(c) >= 2 and c.startswith("`") and c.endswith("`"):
        c = c[1:-1].strip()
    return c


def _is_placeholder(command: str) -> bool:
    c = (command or "").strip()
    if not c:
        return True
    if c.startswith("#"):
        return True
    return any(token in c for token in PLACEHOLDER_TOKENS)


@dataclass
class Finding:
    step_id: str
    code: str
    severity: str
    message: str


@dataclass
class Report:
    track: str
    findings: list[Finding] = field(default_factory=list)
    block_reason: str | None = None

    @property
    def surfaced(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SURFACE]


def _mode(track: str) -> str:
    t = (track or "").strip().upper()
    if t == "XS":
        return "skip"
    if t == "S":
        return "surface"
    return "block"


def _read(ticket: str, name: str) -> str:
    try:
        from core.shared.paths import klc_ticket_meta_file
        return (klc_ticket_meta_file(ticket).parent / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_meta_ro(ticket: str) -> dict:
    try:
        import lifecycle as _lc
        return _lc.read_meta_ro(ticket) or {}
    except Exception:                                  # noqa: BLE001
        return {}


def _repo_root(repo=None) -> Path:
    if repo is not None:
        return Path(repo)
    try:
        from core.shared.paths import project_root
        return project_root()
    except Exception:                                  # noqa: BLE001
        return _project_root_dir


def _waived(ticket: str):
    """The SAME override list Evidence uses (D-005): a list of waived AC ids
    AND step ids, or a bare `True` waiving the whole arm."""
    val = _read_meta_ro(ticket).get("deferred_verify_evidence")
    if val is True:
        return True
    if isinstance(val, list):
        return set(val)
    return set()


def _is_waived(waived, step_id: str) -> bool:
    return waived is True or step_id in waived


def _block_or_surface(report: Report, mode: str, step_id: str, code: str,
                      waived, message: str) -> None:
    if mode == "block" and not _is_waived(waived, step_id):
        report.findings.append(Finding(step_id, code, BLOCK, message))
        report.block_reason = (message if report.block_reason is None
                               else report.block_reason + "; " + message)
    else:
        note = message
        if mode == "block":
            note = message + " — waived via meta.deferred_verify_evidence"
        report.findings.append(Finding(step_id, code, SURFACE, note))


def _surface(report: Report, step_id: str, code: str, message: str) -> None:
    report.findings.append(Finding(step_id, code, SURFACE, message))


def check_steps(ticket: str, track: str, repo=None, *, run_commands: bool,
                deadline: float | None = None, cache: dict | None = None) -> Report:
    """Re-execute each impl-plan step's `VERIFY:` command and compare the
    ISOLATED outcome token in `Expected:` against the captured output
    (AC-8). A placeholder or unlaunchable `VERIFY:` is a blocking finding on
    M/L (AC-9, D-205 — unlike the Evidence arm, `launch-error` blocks here:
    an unlaunchable command is a defect in the plan text the author
    controls). A budget overrun surfaces (D-204); an `Expected:` with no
    outcome token surfaces `expected-unmatchable` rather than blocking.

    *deadline* (review-fix, HIGH): a `time.monotonic()` value shared across
    the WHOLE verification arm for one ack (this module, `evidence_gate`,
    `ac_test_coverage`) — passed down from `can_complete_build` so the total
    ack ceiling is one `verify.arm_budget_seconds`, not one per arm. `None`
    (the default, e.g. a standalone/test call) computes a fresh one.

    *cache* (KLC-114 review round 1, HIGH): an optional per-ack Verdict
    cache, keyed by `(ticket, step_id, command)`, shared with
    `step_ledger.judge_step` so the SAME step's SAME VERIFY command
    executes at most once per `can_complete_build` call rather than once
    per arm. `None` (the default) disables caching — behaviour for every
    other caller (a standalone/test call) is unchanged.
    """
    report, mode = Report(track=track), _mode(track)
    if mode == "skip":
        return report
    plan = _read(ticket, "impl-plan.md")
    if not plan.strip():                      # AC-8 is scoped to "an impl-plan exists"
        _surface(report, "no-impl-plan", "no-impl-plan",
                "impl-plan.md is absent, so the step VERIFY re-run is skipped")
        return report

    budget = settings.verify_step_budget()
    root = _repo_root(repo)
    if deadline is None:
        deadline = time.monotonic() + settings.verify_arm_budget()
    waived = _waived(ticket)

    for step in impl_plan_check.parse_impl_plan_steps(plan):
        sid = step["id"]
        fields = impl_plan_check.extract_step_fields(step["body"])
        command = _clean_command(fields.get("verify", ""))
        expected = fields.get("expected", "")
        if _is_placeholder(command):
            _block_or_surface(report, mode, sid, "verify-placeholder", waived,
                              f"{sid}: VERIFY is a placeholder or not runnable")
            continue
        if not run_commands:
            continue
        if time.monotonic() >= deadline:
            _surface(report, sid, "unverified-arm-budget-exhausted",
                    f"{sid}: unverified: arm-budget-exhausted — the arm budget "
                    f"was spent before this step's VERIFY ran")
            continue
        v = verify_runner.run_cached(cache, (ticket, sid, command), command,
                                     budget_s=budget, cwd=str(root))
        if v.state == verify_runner.UNVERIFIED:
            if v.reason == verify_runner.LAUNCH_ERROR:   # AC-9 "is not runnable" — D-205
                _block_or_surface(report, mode, sid, "verify-unrunnable", waived,
                                  f"{sid}: VERIFY is not runnable ({v.detail})")
            else:                                        # a budget overrun — D-204
                _surface(report, sid, f"unverified-{v.reason}",
                        f"{sid}: unverified: {v.reason} ({v.detail})")
            continue
        if v.state == verify_runner.FAILED:
            _block_or_surface(report, mode, sid, "verify-failed", waived,
                              f"{sid}: VERIFY command exited non-zero (exit {v.exit_code})")
            continue
        token = expected_token(expected)
        if not token:
            _surface(report, sid, "expected-unmatchable",
                    f"{sid}: Expected is prose, so the step was judged on exit "
                    f"status alone")
        elif not _token_in_output(token, v.output):       # AC-8
            _block_or_surface(report, mode, sid, "expected-mismatch", waived,
                              f"{sid}: expected token {token!r} not found in the "
                              f"VERIFY output")
    return report


_SEVERITY = {"verify-placeholder": "medium", "verify-unrunnable": "medium",
            "verify-failed": "medium", "expected-mismatch": "medium"}


def warn_lines(report: Report) -> list[str]:
    return [f"step-verify[{f.code}]: {f.message}" for f in report.surfaced]


def advisory_records(report: Report) -> list[dict]:
    """The KLC-117 record form of `warn_lines` — `source="verify"`, the same
    aggregator stream the Evidence arm and `ac_test_coverage` use."""
    return [{"source": "verify", "severity": _SEVERITY.get(f.code, "info"),
            "code": f"verify.{f.code}", "message": f.message, "ref": f.step_id}
            for f in report.surfaced]
