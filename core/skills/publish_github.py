#!/usr/bin/env python3
"""GitHub publish adapter for KLC-003 — publish a review verdict to the PR.

This module is the forge-facing half of `klc publish`. Given a ticket's
`review-report.md`, it resolves the ticket's GitHub PR and publishes the review
result: a verdict label, a summary comment, and (on CHANGES REQUESTED) a failing
commit status on the PR head SHA.

Design notes (why it looks like this):

- **One injectable `gh` boundary.** Every `gh` invocation goes through
  `run_gh(argv) -> (rc, stdout)`. Production uses a `subprocess.run` default;
  tests inject a recorder so they can assert the EXACT argv constructed for each
  verdict (the KLC-057 "fake that hides behaviour" trap: never assert merely
  "gh was called").
- **Degrade-not-fail (AC-4).** No open PR, `gh` absent, not authenticated, or a
  non-GitHub context is a CLEAN no-op: log one line, return a `Result` with
  `published=False`, never raise. Mirrors the KLC-076 Jira-sentinel precedent.
- **Commit status, not check-run (AC-2).** Check-runs need a GitHub App token;
  the user `gh` token can only write commit statuses. A `failure` status with
  context `klc/review` renders as a red check on the PR.
- **`gh api` placeholder substitution.** `{owner}`/`{repo}` are resolved by `gh`
  from the current repo, so the status call needs no manual repo lookup.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

# --- verdict vocabulary -------------------------------------------------------

APPROVED = "APPROVED"
CHANGES_REQUESTED = "CHANGES_REQUESTED"

LABEL_APPROVED = "review:approved"
LABEL_CHANGES = "review:changes-requested"
STATUS_CONTEXT = "klc/review"

# gh output fields we request for a PR (headRefOid is the head SHA for AC-2).
_PR_JSON_FIELDS = "number,url,state,headRefName,headRefOid"

GhRunner = Callable[[list[str]], "tuple[int, str]"]


# --- the injectable gh boundary ----------------------------------------------

def default_run_gh(argv: list[str]) -> tuple[int, str]:
    """Run `gh <argv>` and return (returncode, stdout).

    gh-absent maps to rc 127 (never a raised FileNotFoundError) so callers treat
    it as just another degrade path. Any other OS error also degrades to 127.
    """
    try:
        proc = subprocess.run(
            ["gh", *argv],
            capture_output=True, text=True, check=False,
        )
        return proc.returncode, proc.stdout
    except (FileNotFoundError, OSError):
        return 127, ""


# --- verdict parsing ----------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^\s*verdict\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)
_VERDICT_LINE_RE = re.compile(
    r"^\s*VERDICT\s+(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)
_VERDICT_SECTION_RE = re.compile(
    r"##\s+Verdict\s*\n(.*?)(?=\n##|\Z)", re.DOTALL | re.IGNORECASE
)
_APPROVE_RE = re.compile(r"\b(APPROVED|PASS|approve|clean)\b")
_REJECT_RE = re.compile(
    r"\b(CHANGES[_ ]REQUESTED|NEEDS[_ ]FIX|REQUEST[_ ]CHANGES|REJECTED)\b",
    re.IGNORECASE,
)


def _classify(blob: str) -> Optional[str]:
    """Map a text blob to APPROVED / CHANGES_REQUESTED / None. Reject wins."""
    if not blob:
        return None
    has_reject = bool(_REJECT_RE.search(blob))
    has_approve = bool(_APPROVE_RE.search(blob))
    if has_reject:
        return CHANGES_REQUESTED
    if has_approve:
        return APPROVED
    return None


def parse_verdict(report_text: str) -> Optional[str]:
    """Extract the review verdict from a `review-report.md`.

    Robust to all three forms the review contract can emit:
      1. YAML frontmatter `verdict: APPROVED`.
      2. a `## Verdict` section.
      3. a bare `VERDICT <APPROVED|CHANGES REQUESTED>` line.
    Returns "APPROVED", "CHANGES_REQUESTED", or None when no verdict is present.
    Reject always wins over approve when both appear (safety-first: a report that
    mentions changes-requested must never publish an approval).
    """
    if not report_text:
        return None

    # Precedence 1: an explicit VERDICT line is the review contract's machine
    # output — most authoritative.
    m = _VERDICT_LINE_RE.search(report_text)
    if m:
        v = _classify(m.group(1))
        if v:
            return v

    # Precedence 2: frontmatter `verdict:` key.
    m = _FRONTMATTER_RE.search(report_text)
    if m:
        v = _classify(m.group(1))
        if v:
            return v

    # Precedence 3: the `## Verdict` section body.
    m = _VERDICT_SECTION_RE.search(report_text)
    if m:
        v = _classify(m.group(1))
        if v:
            return v

    return None


def extract_summary(report_text: str, *, verdict: Optional[str] = None) -> str:
    """Build the PR-comment body from the report's `## Summary` section.

    Falls back to the `## Verdict` section, then to a one-line verdict statement.
    Always prefixed with an attribution line so the comment is self-describing on
    the PR.
    """
    body = ""
    m = re.search(r"##\s+Summary\s*\n(.*?)(?=\n##|\Z)", report_text,
                  re.DOTALL | re.IGNORECASE)
    if m and m.group(1).strip():
        body = m.group(1).strip()
    else:
        m = _VERDICT_SECTION_RE.search(report_text)
        if m and m.group(1).strip():
            body = m.group(1).strip()

    verdict = verdict or parse_verdict(report_text)
    header = "**KLC review**"
    if verdict == APPROVED:
        header += " — APPROVED"
    elif verdict == CHANGES_REQUESTED:
        header += " — CHANGES REQUESTED"
    if not body:
        body = "See the KLC review report for details."
    return f"{header}\n\n{body}"


# --- verdict → action mapping (single well-tested function) -------------------

@dataclass(frozen=True)
class Action:
    """The publish actions implied by a verdict.

    label        — the PR label to add.
    status_state — commit-status state to set on the PR head SHA, or None when
                   the verdict implies no status (APPROVED).
    """
    label: str
    status_state: Optional[str]


def verdict_action(verdict: str) -> Action:
    """Map a verdict string to the label + commit-status it implies.

    The single source of truth for AC-1 / AC-2. Any unknown verdict is a
    programming error (callers gate on `parse_verdict` returning a known value).
    """
    if verdict == APPROVED:
        return Action(label=LABEL_APPROVED, status_state=None)
    if verdict == CHANGES_REQUESTED:
        return Action(label=LABEL_CHANGES, status_state="failure")
    raise ValueError(f"unknown verdict: {verdict!r}")


# --- PR resolution ------------------------------------------------------------

def _ticket_number(ticket: str) -> Optional[str]:
    """Return the numeric part of a ticket id (e.g. 'KLC-003' -> '3')."""
    m = re.search(r"-0*(\d+)\s*$", ticket)
    return m.group(1) if m else None


def _branch_matches_ticket(head_ref: str, ticket: str) -> bool:
    """True when a PR head ref is the ticket's feature branch.

    Convention `feature/klc-<n>-*`, case-insensitive; leading zeros on <n> are
    ignored so `feature/klc-3-x` and `feature/KLC-003-x` both match KLC-003.
    """
    num = _ticket_number(ticket)
    if not num:
        return False
    pat = re.compile(rf"^feature/klc-0*{num}(?:-|$)", re.IGNORECASE)
    return bool(pat.match(head_ref or ""))


@dataclass
class PullRequest:
    number: int
    url: str
    state: str
    head_ref: str
    head_sha: str


def resolve_pr(ticket: str, run_gh: GhRunner,
               branch: Optional[str] = None) -> Optional[PullRequest]:
    """Resolve the ticket's open GitHub PR, or None (clean no-op) if there isn't
    one / this is not a GitHub context.

    - `branch` override → `gh pr view <branch>`.
    - otherwise → `gh pr list --state open` filtered by the ticket's feature
      branch convention.
    Any `gh` failure (rc != 0, including gh-absent rc 127, not-authed, non-forge)
    returns None — never raises.
    """
    if branch:
        rc, out = run_gh(["pr", "view", branch, "--json", _PR_JSON_FIELDS])
        if rc != 0 or not out.strip():
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None
        return _pr_from_json(data)

    rc, out = run_gh(["pr", "list", "--state", "open", "--json", _PR_JSON_FIELDS])
    if rc != 0 or not out.strip():
        return None
    try:
        prs = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(prs, list):
        return None
    for data in prs:
        if _branch_matches_ticket(data.get("headRefName", ""), ticket):
            return _pr_from_json(data)
    return None


def _pr_from_json(data: dict) -> Optional[PullRequest]:
    try:
        return PullRequest(
            number=int(data["number"]),
            url=data.get("url", ""),
            state=data.get("state", ""),
            head_ref=data.get("headRefName", ""),
            head_sha=data.get("headRefOid", ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


# --- the publish operation ----------------------------------------------------

@dataclass
class Result:
    """Outcome of a publish attempt. `published` is False for every no-op."""
    published: bool
    message: str
    verdict: Optional[str] = None
    pr_number: Optional[int] = None
    actions: list[str] = field(default_factory=list)


def publish(ticket: str, report_text: str, run_gh: GhRunner,
            branch: Optional[str] = None) -> Result:
    """Publish the review verdict in `report_text` to the ticket's GitHub PR.

    Degrade-not-fail: every failure to act is a clean no-op Result with
    `published=False`; this function never raises for a forge/context problem.
    """
    verdict = parse_verdict(report_text)
    if verdict is None:
        return Result(False, "no parseable verdict in review-report.md — no-op")

    pr = resolve_pr(ticket, run_gh, branch=branch)
    if pr is None:
        return Result(False,
                      "no open GitHub PR for this ticket (or non-GitHub "
                      "context) — no-op; local report stays authoritative",
                      verdict=verdict)

    action = verdict_action(verdict)
    performed: list[str] = []

    # AC-1/AC-2: label (create idempotently, then add). Label-create failures
    # (already exists) are swallowed — the add is what matters.
    color = "0E8A16" if verdict == APPROVED else "D93F0B"
    run_gh(["label", "create", action.label, "--color", color,
            "--description", "KLC review verdict"])
    run_gh(["pr", "edit", str(pr.number), "--add-label", action.label])
    performed.append(f"label:{action.label}")

    # AC-2: failing commit status on the PR head SHA.
    if action.status_state is not None and pr.head_sha:
        run_gh(["api", f"repos/{{owner}}/{{repo}}/statuses/{pr.head_sha}",
                "-f", f"state={action.status_state}",
                "-f", f"context={STATUS_CONTEXT}",
                "-f", "description=KLC review requested changes"])
        performed.append(f"status:{action.status_state}")

    # AC-3: summary comment.
    body = extract_summary(report_text, verdict=verdict)
    run_gh(["pr", "comment", str(pr.number), "--body", body])
    performed.append("comment")

    return Result(True,
                  f"published {verdict} to PR #{pr.number}",
                  verdict=verdict, pr_number=pr.number, actions=performed)
