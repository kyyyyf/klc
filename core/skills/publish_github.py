#!/usr/bin/env python3
"""GitHub publish adapter for KLC-003 — publish a review verdict to the PR.

This module is the forge-facing half of `klc publish`. Given a ticket's
`review-report.md`, it resolves the ticket's GitHub PR and publishes the review
result: a verdict label, a summary comment (deduplicated across re-runs via a
hidden marker), and — on CHANGES REQUESTED — a failing commit status on the PR
head SHA.

Design notes (why it looks like this):

- **One injectable `gh` boundary.** Every `gh` invocation goes through
  `run_gh(argv) -> (rc, stdout)`. Production uses a `subprocess.run` default;
  tests inject a recorder so they can assert the EXACT argv constructed for each
  verdict (the KLC-057 "fake that hides behaviour" trap: never assert merely
  "gh was called"). NOTHING in this module or its tests may reach a real `gh`.
- **Degrade-not-fail (AC-4).** No open PR, `gh` absent, not authenticated, a
  non-GitHub context, a closed/merged PR, or an ambiguous multi-PR match is a
  CLEAN no-op: it returns a `Result` with `published=False` and never raises.
  The library itself never raises for a forge/context problem — the verb's
  outer `except` is belt-and-suspenders, not the contract. Mirrors the KLC-076
  Jira-sentinel precedent.
- **Write-failure detection.** Every mutating `gh` call's rc is checked; an
  action is only reported in `Result.actions` when it actually succeeded (rc 0),
  and any failure is surfaced in `Result.failures` with `published=False`. A
  read-only token that cannot write, or a comment that fails after the label
  landed, is NEVER reported as success.
- **Commit status, not check-run (AC-2).** Check-runs need a GitHub App token;
  the user `gh` token can only write commit statuses. A `failure` status with
  context `klc/review` renders as a red check on the PR.
- **`gh api` placeholder substitution.** `{owner}`/`{repo}` are resolved by `gh`
  from the current repo, so the status/comment API calls need no manual repo
  lookup.
- **Conservative verdict parsing.** `parse_verdict` is deliberately reject-wins
  across the WHOLE document: if any "changes requested" token appears anywhere,
  the verdict is CHANGES REQUESTED regardless of any APPROVED token. This can
  only ever err toward NOT publishing an approval — it never falsely approves.
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

# Hidden HTML-comment marker embedded in the PR comment body so a re-run can find
# and edit the previous comment instead of posting a duplicate (M5).
_MARKER_TMPL = "<!-- klc:review:{ticket} -->"

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

# Recognized *declaration* forms — presence of at least one tells us a verdict
# was actually stated (vs. incidental prose). All are case-insensitive.
#
#  1. Heading-inline `## Verdict: <V>` — the PRIMARY real format emitted by
#     core/templates/review-report.md.j2 (`## Verdict: {{ verdict }}`).
#  2. Bare trailing `VERDICT <V>` line — the review.md machine contract.
#  3. Frontmatter `verdict: <V>` — the ticket-artifact form (KLC-021 et al.).
#  4. Heading-then-body `## Verdict\n<body>` — a hand-written section form.
_HEADING_INLINE_RE = re.compile(
    r"^\s*#{1,6}\s*Verdict\s*:\s*(\S.*?)\s*$", re.IGNORECASE | re.MULTILINE
)
_VERDICT_LINE_RE = re.compile(
    r"^\s*VERDICT\s+(\S.*?)\s*$", re.IGNORECASE | re.MULTILINE
)
_FRONTMATTER_RE = re.compile(
    r"^\s*verdict\s*:\s*(\S.*?)\s*$", re.IGNORECASE | re.MULTILINE
)
_HEADING_SECTION_RE = re.compile(
    r"^\s*#{1,6}\s*Verdict\s*$\n(.*?)(?=\n#{1,6}\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

_APPROVE_RE = re.compile(r"\bapprov\w*\b", re.IGNORECASE)
_REJECT_RE = re.compile(
    r"\b(?:changes[\s_-]+requested|needs[\s_-]+fix"
    r"|request[\s_-]+changes|rejected)\b",
    re.IGNORECASE,
)


def _classify_token(value: str) -> Optional[str]:
    """Classify a single declared verdict value. Reject-wins within the value."""
    if _REJECT_RE.search(value):
        return CHANGES_REQUESTED
    if _APPROVE_RE.search(value):
        return APPROVED
    return None


def _structured_verdicts(text: str) -> list[str]:
    """Return the raw values of all STRUCTURED verdict declarations.

    Structured = the machine-contract forms whose value sits right after the
    marker: heading-inline `## Verdict: <V>`, the trailing `VERDICT <V>` line,
    and frontmatter `verdict: <V>`. The `## Verdict`-heading-then-body section is
    deliberately NOT structured — its body is prose (handled by the tier-2
    fallback), so a stray phrase in it can never override a machine field.
    """
    return (
        _HEADING_INLINE_RE.findall(text)
        + _VERDICT_LINE_RE.findall(text)
        + _FRONTMATTER_RE.findall(text)
    )


def _has_verdict_declaration(text: str) -> bool:
    """True when the report states a verdict in any recognized form (incl. the
    prose `## Verdict` section) — the gate for the tier-2 fallback."""
    return bool(
        _HEADING_INLINE_RE.search(text)
        or _VERDICT_LINE_RE.search(text)
        or _FRONTMATTER_RE.search(text)
        or _HEADING_SECTION_RE.search(text)
    )


def parse_verdict(report_text: str) -> Optional[str]:
    """Extract the review verdict from a `review-report.md`.

    Two-tier precedence so an authoritative machine field is never overridden by
    incidental body prose (codex P2 over-reach fix), while staying conservative:

    Tier 1 — STRUCTURED declarations are authoritative. Collect every value from
    the machine-contract forms (heading-inline `## Verdict: <V>` — the j2
    template's PRIMARY form; the trailing `VERDICT <V>` line; frontmatter
    `verdict:`). If ANY structured declaration exists, decide from the structured
    set ONLY, reject-wins AMONG them: any structured CHANGES REQUESTED ⇒
    CHANGES_REQUESTED; else a structured APPROVED ⇒ APPROVED; else None (e.g.
    `## Verdict: PENDING`). Body prose is ignored in this tier — so
    `## Verdict: APPROVED` followed by "no changes requested" stays APPROVED.

    Tier 2 — fallback ONLY when no structured declaration exists. If a prose
    `## Verdict` section is present, do the conservative whole-document reject-
    wins scan (any reject token ⇒ CHANGES_REQUESTED; else an approve token ⇒
    APPROVED). Incidental prose with no verdict declaration at all ⇒ None.

    Both tiers can only ever err toward NOT approving — never a false APPROVED
    (fresh M3 + codex P1/P2 + L8). Returns "APPROVED", "CHANGES_REQUESTED", or
    None.
    """
    if not report_text:
        return None

    # Tier 1: structured declarations win outright.
    structured = _structured_verdicts(report_text)
    if structured:
        classified = [_classify_token(v) for v in structured]
        if CHANGES_REQUESTED in classified:
            return CHANGES_REQUESTED
        if APPROVED in classified:
            return APPROVED
        return None  # declared but named neither outcome (e.g. "PENDING")

    # Tier 2: no structured field — fall back to a whole-document prose scan,
    # but only when a `## Verdict` section actually declares the intent to state
    # a verdict (incidental prose never triggers one).
    if not _has_verdict_declaration(report_text):
        return None
    if _REJECT_RE.search(report_text):
        return CHANGES_REQUESTED
    if _APPROVE_RE.search(report_text):
        return APPROVED
    return None


def extract_summary(report_text: str, *, verdict: Optional[str] = None) -> str:
    """Build the PR-comment body from the report's `## Summary` section.

    Falls back to the `## Verdict` section, then to a one-line statement. Always
    prefixed with an attribution header so the comment is self-describing on the
    PR. The hidden dedupe marker is appended by `publish`, not here.
    """
    body = ""
    m = re.search(r"^\s*#{1,6}\s*Summary\s*$\n(.*?)(?=\n#{1,6}\s|\Z)",
                  report_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if m and m.group(1).strip():
        body = m.group(1).strip()
    else:
        m = _HEADING_SECTION_RE.search(report_text)
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
    """Return the normalized numeric part of a ticket id ('KLC-003' -> '3')."""
    m = re.search(r"-0*(\d+)\s*$", ticket)
    return m.group(1) if m else None


def _branch_ticket_number(branch: str) -> Optional[str]:
    """Return the normalized ticket number a feature branch names, or None.

    `feature/klc-003-x` and `feature/KLC-3-x` both yield '3'. A branch that does
    not follow the convention yields None (the caller then trusts the operator's
    explicit `--branch` choice).
    """
    m = re.match(r"^feature/klc-0*(\d+)(?:-|$)", branch or "", re.IGNORECASE)
    return m.group(1) if m else None


def _branch_matches_ticket(head_ref: str, ticket: str) -> bool:
    """True when a PR head ref is the ticket's feature branch.

    Convention `feature/klc-<n>-*`, case-insensitive; leading zeros on <n> are
    ignored so `feature/klc-3-x` and `feature/KLC-003-x` both match KLC-003.
    """
    num = _ticket_number(ticket)
    if not num:
        return False
    return _branch_ticket_number(head_ref) == num


@dataclass
class PullRequest:
    number: int
    url: str
    state: str
    head_ref: str
    head_sha: str

    def is_open(self) -> bool:
        return (self.state or "").upper() == "OPEN"


@dataclass
class PRResolution:
    """Outcome of resolving a ticket to its GitHub PR.

    `pr` is set only on `reason == "ok"`. Every other reason is a clean no-op
    with an explanatory `detail`.
    """
    pr: Optional[PullRequest]
    reason: str          # ok | none | unavailable | closed | ambiguous | branch-mismatch
    detail: str = ""


def _pr_from_json(data: dict) -> Optional[PullRequest]:
    if not isinstance(data, dict):
        return None
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


def resolve_pr(ticket: str, run_gh: GhRunner,
               branch: Optional[str] = None) -> PRResolution:
    """Resolve the ticket's open GitHub PR. Always returns a `PRResolution`;
    never raises.

    - `branch` override → `gh pr view <branch>`. If the override names a DIFFERENT
      ticket's feature branch, refuse (branch-mismatch) so a typo cannot publish
      to the wrong PR (L9).
    - otherwise → `gh pr list --state open`, keep the PRs whose head ref matches
      the ticket convention; >1 match → ambiguous no-op (M6).
    A non-OPEN PR is a `closed` no-op in BOTH paths (M2). Any `gh` failure
    (rc != 0, incl. gh-absent rc 127, not-authed, non-forge) → `unavailable`.
    """
    if branch:
        override_num = _branch_ticket_number(branch)
        tnum = _ticket_number(ticket)
        if override_num is not None and tnum is not None and override_num != tnum:
            return PRResolution(
                None, "branch-mismatch",
                f"--branch {branch!r} names ticket #{override_num}, "
                f"not {ticket}",
            )
        rc, out = run_gh(["pr", "view", branch, "--json", _PR_JSON_FIELDS])
        if rc != 0:
            return PRResolution(None, "unavailable",
                                "gh could not view the branch PR")
        if not out.strip():
            return PRResolution(None, "none")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return PRResolution(None, "unavailable", "unparseable gh output")
        pr = _pr_from_json(data)
        if pr is None:
            return PRResolution(None, "unavailable", "unexpected gh payload")
        if not pr.is_open():
            return PRResolution(None, "closed",
                                f"PR #{pr.number} is {pr.state}")
        return PRResolution(pr, "ok")

    rc, out = run_gh(["pr", "list", "--state", "open", "--json", _PR_JSON_FIELDS])
    if rc != 0:
        return PRResolution(None, "unavailable",
                            "gh unavailable / not a GitHub context")
    if not out.strip():
        return PRResolution(None, "none")
    try:
        prs = json.loads(out)
    except json.JSONDecodeError:
        return PRResolution(None, "unavailable", "unparseable gh output")
    if not isinstance(prs, list):
        return PRResolution(None, "unavailable", "unexpected gh payload")

    matches: list[PullRequest] = []
    for data in prs:
        if not isinstance(data, dict):
            continue  # L7: never raise on a malformed element
        if _branch_matches_ticket(data.get("headRefName", ""), ticket):
            pr = _pr_from_json(data)
            if pr is not None:
                matches.append(pr)

    open_matches = [p for p in matches if p.is_open()]
    if not open_matches:
        # matched-but-closed vs. no-match-at-all: both are clean no-ops.
        return PRResolution(None, "closed" if matches else "none")
    if len(open_matches) > 1:
        nums = ", ".join(f"#{p.number}" for p in open_matches)
        return PRResolution(None, "ambiguous",
                            f"multiple open PRs match {ticket}: {nums}")
    return PRResolution(open_matches[0], "ok")


# --- the publish operation ----------------------------------------------------

@dataclass
class Result:
    """Outcome of a publish attempt.

    published — True only when a PR was resolved AND every attempted write
                succeeded. Any no-op or partial/failed write → False.
    actions   — writes that actually succeeded (rc 0).
    failures  — writes that were attempted but failed (rc != 0).
    """
    published: bool
    message: str
    verdict: Optional[str] = None
    pr_number: Optional[int] = None
    actions: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


_NOOP_MESSAGE = {
    "none": "no open GitHub PR for this ticket (or non-GitHub context)",
    "unavailable": "gh unavailable / not a GitHub context",
    "closed": "the matching PR is not OPEN (merged/closed)",
    "ambiguous": "multiple open PRs match this ticket — refusing to guess",
    "branch-mismatch": "the --branch override names a different ticket",
}


def _parse_comment_listing(out: str) -> list[dict]:
    """Parse a `gh api` comment listing into a flat list of comment dicts.

    Robust to both shapes that reach us:
      - JSONL — one object per line — from `gh api --paginate --jq ...` spanning
        every page (the real path; codex P2);
      - a single JSON array — an unpaginated / single-page response.
    Malformed lines are skipped; never raises.
    """
    out = out.strip()
    if not out:
        return []
    # A single top-level JSON value (array or object) parses whole.
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    if isinstance(data, dict):
        return [data]
    # Otherwise treat as JSONL (multiple top-level objects, one per line).
    result: list[dict] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            result.append(obj)
    return result


def _find_existing_comment_id(ticket: str, pr_number: int,
                              run_gh: GhRunner) -> Optional[int]:
    """Return the id of a prior KLC review comment on the PR, or None (M5).

    Matches the hidden marker in the comment body. `--paginate` walks EVERY page
    of comments (codex P2 — otherwise a marker beyond the first page is missed
    and a duplicate is posted); `--jq` reduces each to `{id, body}`. Any gh
    failure → None (fall back to posting a fresh comment); never raises.
    """
    marker = _MARKER_TMPL.format(ticket=ticket)
    rc, out = run_gh(
        ["api", f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments",
         "--paginate", "--jq", ".[] | {id: .id, body: .body}"]
    )
    if rc != 0 or not out.strip():
        return None
    for c in _parse_comment_listing(out):
        if marker in (c.get("body") or ""):
            cid = c.get("id")
            if isinstance(cid, int):
                return cid
    return None


def publish(ticket: str, report_text: str, run_gh: GhRunner,
            branch: Optional[str] = None) -> Result:
    """Publish the review verdict in `report_text` to the ticket's GitHub PR.

    Degrade-not-fail: every failure to resolve/act is a clean `Result` with
    `published=False`; this function never raises for a forge/context problem.
    """
    verdict = parse_verdict(report_text)
    if verdict is None:
        return Result(False, "no parseable verdict in review-report.md — no-op")

    res = resolve_pr(ticket, run_gh, branch=branch)
    if res.pr is None:
        base = _NOOP_MESSAGE.get(res.reason, "no PR resolved")
        detail = f" ({res.detail})" if res.detail else ""
        return Result(False,
                      f"{base}{detail} — no-op; local report stays authoritative",
                      verdict=verdict)
    pr = res.pr

    action = verdict_action(verdict)
    performed: list[str] = []
    failures: list[str] = []

    # AC-1/AC-2: label. Create idempotently (already-exists is expected → rc
    # ignored); the ADD is the write whose rc matters.
    color = "0E8A16" if verdict == APPROVED else "D93F0B"
    run_gh(["label", "create", action.label, "--color", color,
            "--description", "KLC review verdict"])
    rc, _ = run_gh(["pr", "edit", str(pr.number), "--add-label", action.label])
    (performed if rc == 0 else failures).append(f"label:{action.label}")

    # AC-2: failing commit status on the PR head SHA.
    if action.status_state is not None:
        if pr.head_sha:
            rc, _ = run_gh(
                ["api", f"repos/{{owner}}/{{repo}}/statuses/{pr.head_sha}",
                 "-f", f"state={action.status_state}",
                 "-f", f"context={STATUS_CONTEXT}",
                 "-f", "description=KLC review requested changes"]
            )
            (performed if rc == 0 else failures).append(
                f"status:{action.status_state}")
        else:
            failures.append("status:no-head-sha")

    # AC-3: summary comment, deduplicated via the hidden marker (M5).
    marker = _MARKER_TMPL.format(ticket=ticket)
    body = f"{extract_summary(report_text, verdict=verdict)}\n\n{marker}"
    existing = _find_existing_comment_id(ticket, pr.number, run_gh)
    if existing is not None:
        rc, _ = run_gh(
            ["api", "--method", "PATCH",
             f"repos/{{owner}}/{{repo}}/issues/comments/{existing}",
             "-f", f"body={body}"]
        )
        (performed if rc == 0 else failures).append("comment:updated")
    else:
        rc, _ = run_gh(["pr", "comment", str(pr.number), "--body", body])
        (performed if rc == 0 else failures).append("comment")

    if failures:
        return Result(False,
                      f"partial publish to PR #{pr.number}: "
                      f"failed [{', '.join(failures)}]",
                      verdict=verdict, pr_number=pr.number,
                      actions=performed, failures=failures)
    return Result(True,
                  f"published {verdict} to PR #{pr.number}",
                  verdict=verdict, pr_number=pr.number, actions=performed)
