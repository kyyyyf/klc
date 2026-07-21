"""KLC-003 — `klc publish` GitHub adapter: unit + read-only-invariant coverage.

SAFETY (H1): NO test may reach a real `gh`. Every unit test injects a
`GhRecorder`; every verb-level test runs the phase IN-PROCESS with
`publish_github.default_run_gh` monkeypatched to a recorder (a subprocess cannot
be monkeypatched, and `gh` resolves its repo from the process CWD ignoring
PROJECT_ROOT, so a real `gh` in a subprocess could mutate a live PR). The single
end-to-end dispatch test shadows `gh` on PATH with a stub binary that always
fails, so even that path provably cannot touch a real PR. The only live touch is
`gh --version` (read-only; mutates nothing).

`GhRecorder.has(*tokens)` asserts the tokens appear as a CONTIGUOUS subsequence
of some recorded argv (adjacency), not merely present somewhere (L11).
"""
from __future__ import annotations

import importlib.util
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

    `responses` maps `tuple(argv[:2])` to `(rc, stdout)`. Unmatched calls return
    (0, "") so writes succeed silently while their argv is still recorded.
    """
    def __init__(self, responses=None):
        self.calls: list[list[str]] = []
        self.responses = responses or {}

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        return self.responses.get(tuple(argv[:2]), (0, ""))

    def has(self, *tokens):
        """First recorded call containing `tokens` as a contiguous subsequence."""
        toks = list(tokens)
        n = len(toks)
        for c in self.calls:
            for i in range(len(c) - n + 1):
                if c[i:i + n] == toks:
                    return c
        return None


APPROVED_REPORT = """---
ticket: KLC-003
verdict: APPROVED
---
# KLC-003 review report

## Summary

Zero blocking findings this pass.

## Verdict

VERDICT APPROVED
"""

CHANGES_REPORT = """---
ticket: KLC-003
verdict: CHANGES REQUESTED
---
# KLC-003 review report

## Summary

Two blocking findings this pass.

## Verdict

VERDICT CHANGES REQUESTED
"""

PR_LIST_JSON = json.dumps([
    {"number": 42, "url": "https://github.com/o/r/pull/42", "state": "OPEN",
     "headRefName": "feature/klc-003-publish-review", "headRefOid": "abc123"},
])


# --- real j2 template rendering (codex P1: the PRIMARY real format) -----------

def _render_j2(verdict: str) -> str:
    """Render the ACTUAL review-report.md.j2 with a minimal context.

    This produces the heading-inline `## Verdict: <verdict>` form that the
    review pipeline really emits — the form the previous parser silently missed.
    """
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    env = Environment(
        loader=FileSystemLoader(str(FW_ROOT / "core" / "templates")),
        undefined=StrictUndefined, keep_trailing_newline=True,
        trim_blocks=True, lstrip_blocks=True,
    )
    tpl = env.get_template("review-report.md.j2")
    return tpl.render(
        timestamp="2026-07-21T00:00:00Z", spec_path="spec.md",
        reviewers=[{"label": "internal", "total": 0, "blocking": 0,
                    "skipped": False}],
        external=None,
        blocking_issues="None", non_blocking_issues="None",
        out_of_scope_issues="None",
        verdict=verdict, adrs=[], tier_classification=None,
        sentinel_matches=None,
    )


def test_parse_real_j2_verdict_approved():
    rendered = _render_j2("APPROVED")
    assert "## Verdict: APPROVED" in rendered  # sanity: heading-inline form
    assert pg.parse_verdict(rendered) == pg.APPROVED


def test_parse_real_j2_verdict_changes_requested():
    rendered = _render_j2("CHANGES REQUESTED")
    assert "## Verdict: CHANGES REQUESTED" in rendered
    assert pg.parse_verdict(rendered) == pg.CHANGES_REQUESTED


# --- verdict parsing: all forms + reject-wins + case ---------------------------

def test_parse_verdict_frontmatter_approved():
    assert pg.parse_verdict("---\nverdict: APPROVED\n---\n") == pg.APPROVED


def test_parse_verdict_frontmatter_changes():
    assert pg.parse_verdict("---\nverdict: CHANGES REQUESTED\n---\n") \
        == pg.CHANGES_REQUESTED


def test_parse_verdict_heading_inline():
    assert pg.parse_verdict("## Verdict: APPROVED\n") == pg.APPROVED
    assert pg.parse_verdict("## Verdict: CHANGES REQUESTED\n") \
        == pg.CHANGES_REQUESTED


def test_parse_verdict_bare_line():
    assert pg.parse_verdict("blah\nVERDICT CHANGES REQUESTED\n") \
        == pg.CHANGES_REQUESTED


def test_parse_verdict_section_body():
    assert pg.parse_verdict("# r\n\n## Verdict\n\nThe code is APPROVED.\n") \
        == pg.APPROVED


def test_parse_verdict_lowercase_and_approved_variants():
    assert pg.parse_verdict("## Verdict: approved") == pg.APPROVED
    assert pg.parse_verdict("---\nverdict: Approval granted\n---") == pg.APPROVED


def test_structured_reject_wins_among_declarations():
    # two STRUCTURED verdicts disagree → reject-wins among them (fresh M3)
    assert pg.parse_verdict(
        "VERDICT APPROVED\n## Verdict: CHANGES REQUESTED\n"
    ) == pg.CHANGES_REQUESTED
    # frontmatter APPROVED + heading-inline CHANGES REQUESTED (both structured)
    assert pg.parse_verdict(
        "---\nverdict: APPROVED\n---\n## Verdict: CHANGES REQUESTED\n"
    ) == pg.CHANGES_REQUESTED


def test_structured_verdict_beats_body_prose():
    # codex P2 over-reach fix: an authoritative `## Verdict: APPROVED` is NOT
    # flipped by a reject phrase that merely appears in the body prose.
    assert pg.parse_verdict(
        "## Verdict: APPROVED\n\nNo changes requested were needed this pass.\n"
    ) == pg.APPROVED
    assert pg.parse_verdict(
        "## Verdict: APPROVED\n\n(the previous pass was rejected)\n"
    ) == pg.APPROVED
    # frontmatter (structured) APPROVED likewise beats body prose
    assert pg.parse_verdict(
        "---\nverdict: APPROVED\n---\n\nEarlier findings: changes requested.\n"
    ) == pg.APPROVED


def test_tier2_prose_reject_wins_when_no_structured_declaration():
    # no structured field, only a `## Verdict` section → tier-2 whole-doc scan
    assert pg.parse_verdict(
        "# r\n\n## Verdict\n\nThe reviewer concluded: changes requested.\n"
    ) == pg.CHANGES_REQUESTED


def test_parse_verdict_none_when_absent():
    assert pg.parse_verdict("# report\n\nno verdict here\n") is None
    assert pg.parse_verdict("") is None
    # a declaration that names neither outcome → None, never a default APPROVED
    assert pg.parse_verdict("## Verdict: PENDING\n") is None


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

    assert gh.has("pr", "edit", "42", "--add-label", "review:approved")
    assert gh.has("label", "create", "review:approved")
    assert gh.has("pr", "comment", "42", "--body")
    # APPROVED sets NO commit status (no statuses api anywhere)
    assert not any("statuses" in " ".join(c) for c in gh.calls)


# --- exact argv: CHANGES REQUESTED --------------------------------------------

def test_publish_changes_exact_argv():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    res = pg.publish("KLC-003", CHANGES_REPORT, gh)
    assert res.published and res.verdict == pg.CHANGES_REQUESTED

    assert gh.has("pr", "edit", "42", "--add-label", "review:changes-requested")
    # failing commit status on the head SHA via gh api, exact payload (adjacency)
    assert gh.has("api", "repos/{owner}/{repo}/statuses/abc123")
    assert gh.has("-f", "state=failure")
    assert gh.has("-f", "context=klc/review")
    assert gh.has("pr", "comment", "42", "--body")


def test_comment_body_carries_summary_and_marker():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    pg.publish("KLC-003", CHANGES_REPORT, gh)
    comment = gh.has("pr", "comment", "42", "--body")
    body = comment[comment.index("--body") + 1]
    assert "two blocking findings" in body.lower()
    assert "CHANGES REQUESTED" in body            # attribution header
    assert "<!-- klc:review:KLC-003 -->" in body  # dedupe marker (M5)


# --- comment dedupe: edit an existing marked comment (M5) ---------------------

def test_comment_dedupe_edits_existing_comment():
    marker = "<!-- klc:review:KLC-003 -->"
    comments = json.dumps([{"id": 555, "body": f"stale body\n{marker}"}])
    gh = GhRecorder({
        ("pr", "list"): (0, PR_LIST_JSON),
        ("api", "repos/{owner}/{repo}/issues/42/comments"): (0, comments),
    })
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published and "comment:updated" in res.actions
    # PATCH the existing comment id, NOT a fresh pr comment
    assert gh.has("api", "--method", "PATCH",
                  "repos/{owner}/{repo}/issues/comments/555")
    assert gh.has("pr", "comment") is None
    # the lookup must paginate every page (codex P2)
    listing = gh.has("api", "repos/{owner}/{repo}/issues/42/comments")
    assert listing is not None and "--paginate" in listing


def test_comment_dedupe_finds_marker_on_a_later_page():
    """codex P2: with `--paginate --jq`, gh emits JSONL across all pages; the
    KLC marker on a LATER page must still be found and the comment EDITED."""
    marker = "<!-- klc:review:KLC-003 -->"
    # JSONL (one object per line) — the marker is on the last line (later page).
    jsonl = "\n".join(json.dumps({"id": i, "body": f"chatter {i}"})
                      for i in range(1, 31))
    jsonl += "\n" + json.dumps({"id": 999, "body": f"prior review\n{marker}"})
    gh = GhRecorder({
        ("pr", "list"): (0, PR_LIST_JSON),
        ("api", "repos/{owner}/{repo}/issues/42/comments"): (0, jsonl),
    })
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published and "comment:updated" in res.actions
    assert gh.has("api", "--method", "PATCH",
                  "repos/{owner}/{repo}/issues/comments/999")
    assert gh.has("pr", "comment") is None  # edited, not duplicated


# --- PR resolution ------------------------------------------------------------

def test_resolve_pr_from_list_matches_ticket_branch():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    res = pg.resolve_pr("KLC-003", gh)
    assert res.reason == "ok" and res.pr.number == 42
    assert res.pr.head_sha == "abc123"
    assert gh.calls[0][:4] == ["pr", "list", "--state", "open"]


def test_resolve_pr_branch_override_uses_pr_view():
    prj = json.dumps({"number": 7, "url": "u", "state": "OPEN",
                      "headRefName": "custom", "headRefOid": "deadbeef"})
    gh = GhRecorder({("pr", "view"): (0, prj)})
    res = pg.resolve_pr("KLC-003", gh, branch="custom")
    assert res.reason == "ok" and res.pr.number == 7
    assert res.pr.head_sha == "deadbeef"
    assert gh.calls[0][:3] == ["pr", "view", "custom"]


def test_resolve_pr_no_match_when_branch_differs():
    other = json.dumps([{"number": 9, "url": "u", "state": "OPEN",
                         "headRefName": "feature/klc-999-x", "headRefOid": "z"}])
    gh = GhRecorder({("pr", "list"): (0, other)})
    res = pg.resolve_pr("KLC-003", gh)
    assert res.pr is None and res.reason == "none"


def test_branch_matches_ignores_leading_zeros_and_case():
    assert pg._branch_matches_ticket("feature/KLC-3-anything", "KLC-003")
    assert pg._branch_matches_ticket("feature/klc-003-x", "KLC-003")
    assert not pg._branch_matches_ticket("feature/klc-30-x", "KLC-003")


# --- M2: closed / merged PR is a clean no-op in BOTH paths --------------------

def test_closed_pr_view_path_is_noop():
    prj = json.dumps({"number": 7, "url": "u", "state": "MERGED",
                      "headRefName": "custom", "headRefOid": "z"})
    gh = GhRecorder({("pr", "view"): (0, prj)})
    res = pg.resolve_pr("KLC-003", gh, branch="custom")
    assert res.pr is None and res.reason == "closed"


def test_closed_pr_list_path_is_noop():
    j = json.dumps([{"number": 42, "url": "u", "state": "CLOSED",
                     "headRefName": "feature/klc-003-x", "headRefOid": "a"}])
    gh = GhRecorder({("pr", "list"): (0, j)})
    res = pg.resolve_pr("KLC-003", gh)
    assert res.pr is None and res.reason == "closed"


# --- M6: ambiguous multi-PR match no-ops rather than guessing -----------------

def test_ambiguous_multi_pr_is_noop():
    j = json.dumps([
        {"number": 42, "url": "u", "state": "OPEN",
         "headRefName": "feature/klc-003-a", "headRefOid": "a"},
        {"number": 43, "url": "u", "state": "OPEN",
         "headRefName": "feature/klc-3-b", "headRefOid": "b"},
    ])
    gh = GhRecorder({("pr", "list"): (0, j)})
    res = pg.resolve_pr("KLC-003", gh)
    assert res.pr is None and res.reason == "ambiguous"


# --- L7: malformed JSON never raises ------------------------------------------

def test_resolve_pr_non_dict_element_does_not_raise():
    gh = GhRecorder({("pr", "list"): (0, "[1, 2, \"x\"]")})
    res = pg.resolve_pr("KLC-003", gh)
    assert res.pr is None and res.reason == "none"


def test_resolve_pr_garbage_json_is_unavailable():
    gh = GhRecorder({("pr", "list"): (0, "not json{")})
    res = pg.resolve_pr("KLC-003", gh)
    assert res.pr is None and res.reason == "unavailable"


# --- L9: --branch override for a different ticket is refused ------------------

def test_branch_override_mismatch_refuses_without_touching_gh():
    gh = GhRecorder()
    res = pg.resolve_pr("KLC-003", gh, branch="feature/klc-999-x")
    assert res.pr is None and res.reason == "branch-mismatch"
    assert gh.calls == []  # short-circuits before any gh call


def test_branch_override_non_convention_is_allowed():
    prj = json.dumps({"number": 7, "url": "u", "state": "OPEN",
                      "headRefName": "hotfix", "headRefOid": "z"})
    gh = GhRecorder({("pr", "view"): (0, prj)})
    res = pg.resolve_pr("KLC-003", gh, branch="hotfix")
    assert res.reason == "ok" and res.pr.number == 7


# --- degrade paths (AC-4) -----------------------------------------------------

def test_degrade_no_open_pr_is_noop():
    gh = GhRecorder({("pr", "list"): (0, "[]")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False
    assert not gh.has("pr", "edit")
    assert not gh.has("pr", "comment")
    assert not gh.has("label", "create")


def test_degrade_gh_absent_rc127_is_noop():
    gh = GhRecorder({("pr", "list"): (127, "")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False
    assert not gh.has("pr", "edit")


def test_degrade_gh_list_error_is_noop():
    gh = GhRecorder({("pr", "list"): (1, "gh: not authenticated")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False


def test_degrade_no_verdict_is_noop_without_resolving():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    res = pg.publish("KLC-003", "# report\nno verdict\n", gh)
    assert res.published is False
    assert gh.calls == []  # resolution never attempted without a verdict


# --- M4 / codex P2a: write failures are not reported as success ---------------

def test_publish_partial_when_label_add_fails():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON),
                     ("pr", "edit"): (1, "HTTP 403")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False
    assert "label:review:approved" in res.failures
    assert "partial" in res.message.lower()


def test_publish_partial_when_comment_fails():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON),
                     ("pr", "comment"): (1, "HTTP 403")})
    res = pg.publish("KLC-003", APPROVED_REPORT, gh)
    assert res.published is False
    assert "comment" in res.failures


def test_publish_partial_when_status_fails():
    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON),
                     ("api", "repos/{owner}/{repo}/statuses/abc123"):
                         (1, "HTTP 422")})
    res = pg.publish("KLC-003", CHANGES_REPORT, gh)
    assert res.published is False
    assert any(f.startswith("status") for f in res.failures)


def test_default_run_gh_missing_binary_maps_to_127(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(subprocess, "run", _boom)
    rc, out = pg.default_run_gh(["pr", "list"])
    assert rc == 127 and out == ""


# --- read-only invariant via the real verb, IN-PROCESS with a stubbed gh ------

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


def _load_phase():
    """Import core/phases/publish.py in-process under a unique module name."""
    spec = importlib.util.spec_from_file_location(
        "klc_phase_publish_test", FW_ROOT / "core" / "phases" / "publish.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_publish_verb_is_read_only_and_uses_stubbed_gh(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _bootstrap(tmp_path, "KLC-003", report=APPROVED_REPORT)
    before = mp.read_bytes()

    gh = GhRecorder({("pr", "list"): (0, PR_LIST_JSON)})
    monkeypatch.setattr(pg, "default_run_gh", gh)  # verb can NOT reach real gh

    rc = _load_phase().run(["KLC-003"])
    assert rc == 0
    assert mp.read_bytes() == before, "publish must not mutate meta.json"
    # provably routed through the injected boundary (no real gh invoked)
    assert gh.has("pr", "edit", "42", "--add-label", "review:approved")


def test_publish_verb_no_report_is_clean_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mp = _bootstrap(tmp_path, "KLC-003", report=None)
    before = mp.read_bytes()
    gh = GhRecorder()
    monkeypatch.setattr(pg, "default_run_gh", gh)

    rc = _load_phase().run(["KLC-003"])
    assert rc == 0
    assert gh.calls == []  # never reached gh
    assert "nothing to publish" in capsys.readouterr().out.lower()
    assert mp.read_bytes() == before


def test_publish_verb_unknown_ticket_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / ".klc").mkdir()
    gh = GhRecorder()
    monkeypatch.setattr(pg, "default_run_gh", gh)
    rc = _load_phase().run(["NOPE-999"])
    assert rc == 1
    assert gh.calls == []  # never reached gh


# --- end-to-end dispatch (scripts/klc → phase) with a STUB gh on PATH ---------

def test_dispatch_end_to_end_cannot_touch_real_gh(tmp_path):
    """Drive the real `klc publish` verb through scripts/klc, but shadow `gh`
    on PATH with a stub that always fails — proving the dispatch wiring reaches
    the adapter and degrades, with NO possibility of hitting a real PR."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_gh = bindir / "gh"
    fake_gh.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_gh.chmod(0o755)

    mp = _bootstrap(tmp_path, "KLC-003", report=APPROVED_REPORT)
    before = mp.read_bytes()
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path),
           "PATH": f"{bindir}:{os.environ.get('PATH', '')}"}
    r = subprocess.run([sys.executable, str(KLC), "publish", "KLC-003"],
                       capture_output=True, text=True, env=env, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "no-op" in r.stdout.lower() or "gh unavailable" in r.stdout.lower()
    assert mp.read_bytes() == before


# --- light live sanity (safe; read-only; no writes) ---------------------------

def test_gh_version_is_safe_sanity_only():
    try:
        p = subprocess.run(["gh", "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        pytest.skip("gh not installed")
    assert p.returncode == 0 and "gh version" in p.stdout
