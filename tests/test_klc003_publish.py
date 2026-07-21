"""KLC-003 — `klc publish` GitHub adapter: unit + read-only-invariant coverage.

No real GitHub calls anywhere. Every `gh` invocation goes through a stubbed
`run_gh` recorder so tests assert the EXACT argv constructed for each verdict
(the KLC-057 "fake that hides behaviour" trap). The one live touch is
`gh --version` as a safe sanity check; it creates/labels/comments nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent
KLC = FW_ROOT / "scripts" / "klc"
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import publish_github as pg  # noqa: E402


# --- stubbed gh boundary ------------------------------------------------------

class GhRecorder:
    """Records every gh argv and replays scripted (rc, stdout) responses.

    `responses` maps a matcher (first two argv tokens, e.g. ('pr','list')) to a
    (rc, stdout). Unmatched calls return (0, "") so action calls (label/comment)
    succeed silently while their argv is still recorded for assertions.
    """
    def __init__(self, responses=None):
        self.calls: list[list[str]] = []
        self.responses = responses or {}

    def __call__(self, argv):
        self.calls.append(list(argv))
        key = tuple(argv[:2])
        return self.responses.get(key, (0, ""))

    def argv_with(self, *tokens):
        """Return the first recorded call containing all `tokens` in order-free."""
        for c in self.calls:
            if all(t in c for t in tokens):
                return c
        return None


APPROVED_REPORT = """---
ticket: KLC-003
verdict: APPROVED
---
# KLC-003 review report

## Summary

APPROVED. Zero blocking findings this pass.

## Verdict

VERDICT APPROVED
"""

CHANGES_REPORT = """---
ticket: KLC-003
verdict: CHANGES REQUESTED
---
# KLC-003 review report

## Summary

Two blocking findings; changes requested.

## Verdict

VERDICT CHANGES REQUESTED
"""

PR_LIST_JSON = json.dumps([
    {"number": 42, "url": "https://github.com/o/r/pull/42", "state": "OPEN",
     "headRefName": "feature/klc-003-publish-review", "headRefOid": "abc123"},
])


# --- verdict parsing ----------------------------------------------------------

def test_parse_verdict_frontmatter_approved():
    assert pg.parse_verdict("---\nverdict: APPROVED\n---\n") == pg.APPROVED


def test_parse_verdict_frontmatter_changes():
    assert pg.parse_verdict("---\nverdict: CHANGES REQUESTED\n---\n") \
        == pg.CHANGES_REQUESTED


def test_parse_verdict_section_only():
    txt = "# r\n\n## Verdict\n\nThe code is APPROVED.\n"
    assert pg.parse_verdict(txt) == pg.APPROVED


def test_parse_verdict_bare_line():
    assert pg.parse_verdict("blah\nVERDICT CHANGES REQUESTED\n") \
        == pg.CHANGES_REQUESTED


def test_parse_verdict_reject_wins_when_both_present():
    txt = "## Verdict\nwas APPROVED earlier but now CHANGES REQUESTED\n"
    assert pg.parse_verdict(txt) == pg.CHANGES_REQUESTED


def test_parse_verdict_none_when_absent():
    assert pg.parse_verdict("# report\n\nno verdict here\n") is None
    assert pg.parse_verdict("") is None


# --- verdict → action mapping -------------------------------------------------

def test_verdict_action_approved():
    a = pg.verdict_action(pg.APPROVED)
    assert a.label == "review:approved" and a.status_state is None


def test_verdict_action_changes():
    a = pg.verdict_action(pg.CHANGES_REQUESTED)
    assert a.label == "review:changes-requested" and a.status_state == "failure"


def test_verdict_action_unknown_raises():
    with pytest.raises(ValueError):
        pg.verdict_action("MAYBE")


# --- exact argv: APPROVED -----------------------------------------------------

def test_publish_approved_exact_argv():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published and res.pr_number == 42 and res.verdict == pg.APPROVED

    # label add on the resolved PR number, correct label name
    assert gh.argv_with("pr", "edit", "42", "--add-label", "review:approved")
    assert gh.argv_with("label", "create", "review:approved")
    # summary comment on the PR
    assert gh.argv_with("pr", "comment", "42", "--body")
    # APPROVED sets NO commit status
    assert gh.argv_with("api") is None
    assert not any("statuses" in " ".join(c) for c in gh.calls)


# --- exact argv: CHANGES REQUESTED --------------------------------------------

def test_publish_changes_exact_argv():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    res = pg.publish("KLC-003", CHANGES_REPORT, gh)
    assert res.published and res.verdict == pg.CHANGES_REQUESTED

    assert gh.argv_with("pr", "edit", "42", "--add-label",
                        "review:changes-requested")
    # failing commit status on the head SHA via gh api, exact payload
    api = gh.argv_with("api")
    assert api is not None
    assert api[1] == "repos/{owner}/{repo}/statuses/abc123"
    assert "state=failure" in api
    assert "context=klc/review" in api
    # comment posted too
    assert gh.argv_with("pr", "comment", "42", "--body")


def test_comment_body_carries_summary():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    pg.publish("KLC-003", CHANGES_REPORT, gh)
    comment = gh.argv_with("pr", "comment", "42", "--body")
    body = comment[comment.index("--body") + 1]
    assert "changes requested" in body.lower()
    assert "CHANGES REQUESTED" in body  # header attribution


# --- PR resolution ------------------------------------------------------------

def test_resolve_pr_from_list_matches_ticket_branch():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    pr = pg.resolve_pr("KLC-003", gh)
    assert pr is not None and pr.number == 42 and pr.head_sha == "abc123"
    # the list argv shape
    assert gh.calls[0][:4] == ["pr", "list", "--state", "open"]


def test_resolve_pr_branch_override_uses_pr_view():
    pr_json = json.dumps({"number": 7, "url": "u", "state": "OPEN",
                          "headRefName": "custom", "headRefOid": "deadbeef"})
    gh = GhRecorder({("pr", "view"): (0, pr_json)})
    pr = pg.resolve_pr("KLC-003", gh, branch="custom")
    assert pr is not None and pr.number == 7 and pr.head_sha == "deadbeef"
    assert gh.calls[0][:3] == ["pr", "view", "custom"]


def test_resolve_pr_no_match_when_branch_differs():
    other = json.dumps([{"number": 9, "url": "u", "state": "OPEN",
                         "headRefName": "feature/klc-999-x", "headRefOid": "z"}])
    gh = GhRecorder({("pr", "list"): (0, other)})
    assert pg.resolve_pr("KLC-003", gh) is None


def test_branch_matches_ignores_leading_zeros_and_case():
    assert pg._branch_matches_ticket("feature/KLC-3-anything", "KLC-003")
    assert pg._branch_matches_ticket("feature/klc-003-x", "KLC-003")
    assert not pg._branch_matches_ticket("feature/klc-30-x", "KLC-003")


# --- degrade paths (AC-4) -----------------------------------------------------

def test_degrade_no_open_pr_is_noop():
    gh = GhRecorder({("pr", "list"): (0, "[]")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False
    # only the resolution call happened; no label/comment/api publish argv
    assert not gh.argv_with("pr", "edit")
    assert not gh.argv_with("pr", "comment")
    assert not gh.argv_with("label", "create")


def test_degrade_gh_absent_rc127_is_noop():
    gh = GhRecorder({("pr", "list"): (127, "")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False
    assert not gh.argv_with("pr", "edit")


def test_degrade_gh_list_error_is_noop():
    gh = GhRecorder({("pr", "list"): (1, "gh: not authenticated")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False


def test_degrade_no_verdict_is_noop():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    res = pg.publish("KLC-003", "# report\nno verdict\n", gh)
    assert res.published is False
    # resolution is never even attempted without a verdict
    assert gh.calls == []


def test_default_run_gh_missing_binary_maps_to_127(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(subprocess, "run", _boom)
    rc, out = pg.default_run_gh(["pr", "list"])
    assert rc == 127 and out == ""


# --- read-only invariant via the real verb -----------------------------------

def _bootstrap(root: Path, ticket: str, *, report: str | None) -> Path:
    tdir = root / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "feature", "phase": "review:ack",
            "track": "M", "affected_modules": [],
            "created": "2026-01-01T00:00:00Z"}
    mp = tdir / "meta.json"
    mp.write_text(json.dumps(meta), encoding="utf-8")
    if report is not None:
        (tdir / "review-report.md").write_text(report, encoding="utf-8")
    return mp


def _run(args, root):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True,
                          env={**os.environ, "PROJECT_ROOT": str(root)})


def test_publish_verb_is_read_only_meta_unchanged(tmp_path):
    # No PR exists in the tmp repo, so this exercises the degrade path end-to-end
    # through scripts/klc while asserting meta.json is byte-identical afterward.
    mp = _bootstrap(tmp_path, "KLC-003", report=APPROVED_REPORT)
    before = mp.read_bytes()
    r = _run(["publish", "KLC-003"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert mp.read_bytes() == before, "publish must not mutate meta.json"


def test_publish_verb_no_report_is_clean_noop(tmp_path):
    mp = _bootstrap(tmp_path, "KLC-003", report=None)
    before = mp.read_bytes()
    r = _run(["publish", "KLC-003"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "nothing to publish" in r.stdout.lower()
    assert mp.read_bytes() == before


def test_publish_verb_unknown_ticket_errors(tmp_path):
    (tmp_path / ".klc").mkdir()
    r = _run(["publish", "NOPE-999"], tmp_path)
    assert r.returncode == 1
    assert "unknown ticket" in r.stderr.lower()


# --- light live sanity (safe; no writes) --------------------------------------

def test_gh_version_is_safe_sanity_only():
    try:
        p = subprocess.run(["gh", "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        pytest.skip("gh not installed")
    assert p.returncode == 0 and "gh version" in p.stdout
