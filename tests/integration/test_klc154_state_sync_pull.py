"""tests/integration/test_klc154_state_sync_pull.py — KLC-154 step-7,
external review F-2 (MEDIUM): neither the dry run nor the real run pulled
`klc-state` before reading it — the read-only pre-plan decided
unchanged/failed/would-rewrite before any pull, so a straggler another
peer pushed was invisible, and the re-run meant to confirm zero (AC-5)
certified only the LOCAL copy, not the shared state.

Fixed (step-7) by `_sync_state_or_refuse`: the real run calls
`state_sync.pull_rebase_preserving` once at the very start, when the
multi-user feature is ON, and refuses loudly (`MigrationRefused`, exit 2)
if that pull itself fails.

Step-8 (external review F-3): the step-7 fix made the DRY RUN call that
same pull too — which stashes/pops (and on a stash-pop conflict,
`git reset --hard`s) the klc-state worktree, contradicting AC-1's "writes
nothing and takes no lock". The dry run now gets its OWN, non-mutating
check instead (`_check_dry_run_not_stale`): fetch the upstream and refuse
(exit 2) when the local branch is behind it, or when the fetch itself
fails. The real run is unaffected — it keeps the full pull.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402


def test_dry_run_refuses_when_local_klc_state_is_behind_its_upstream(tmp_path, monkeypatch):
    """Step-8 (external review F-3): a peer pushes an old-shape straggler
    directly to the bare remote, bypassing our own worktree entirely —
    exactly what leaves the local branch behind its upstream. AC-1 says
    the dry run "writes nothing and takes no lock"; it may no longer PULL
    to see this straggler (that would stash/merge the worktree). Instead
    it fetches, notices it is behind, and refuses loudly (exit 2) rather
    than silently reporting a stale `unchanged`/`would-rewrite` plan."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    support.add_ticket(tickets, "KLC-9b1", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    bound = support.seed_git_state(tmp_path)

    old = support.old_independent(1)
    support.push_peer_update(
        bound, tmp_path, "tickets/KLC-9b1/spec-review-findings.json", json.dumps(old))

    with pytest.raises(findings_migrate.MigrationRefused) as exc_info:
        findings_migrate.migrate(tickets, dry_run=True)
    assert "behind" in str(exc_info.value)

    code = findings_migrate.cli(tickets, dry_run=True)
    assert code == 2


def test_dry_run_never_pulls_stashes_or_resets_the_worktree(tmp_path, monkeypatch):
    """Step-8 (external review F-3): the dry run must leave the klc-state
    worktree exactly as found — HEAD unchanged, an uncommitted TRACKED
    edit untouched (never stashed/popped/reset), and nothing stashed —
    even though the step-7 code pulled (and could stash/reset) in
    dry-run mode too. The ticket itself has NOTHING to migrate (and the
    dirtied file, `meta.json`, is not one this migration ever touches), so
    this isolates the GLOBAL up-front sync check (`_check_dry_run_not_
    stale`, F-3) from the per-ticket plan-aware dirty-tree check (F-2,
    covered separately in test_klc154_crash_recovery.py) — the ticket
    stays `unchanged`, never `needs-attention`, and the worktree is
    provably untouched throughout."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    support.add_ticket(tickets, "KLC-9b5", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    support.seed_git_state(tmp_path)
    klc = tickets.parent

    before_head = support._git(klc, "rev-parse", "HEAD").strip()
    meta_path = tickets / "KLC-9b5" / "meta.json"
    dirty_text = meta_path.read_text(encoding="utf-8") + "\n"
    meta_path.write_text(dirty_text, encoding="utf-8")

    report = findings_migrate.migrate(tickets, dry_run=True)
    assert report["tickets"][0]["status"] == "unchanged", report["tickets"][0]

    after_head = support._git(klc, "rev-parse", "HEAD").strip()
    assert after_head == before_head
    assert meta_path.read_text(encoding="utf-8") == dirty_text
    stash_list = support._git(klc, "stash", "list")
    assert stash_list.strip() == ""


def test_dry_run_refuses_when_the_fetch_itself_fails(tmp_path, monkeypatch):
    """Step-8 (external review F-3): a fetch failure (network, auth, …)
    refuses the dry run too, rather than silently falling through to a
    stale local read."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-9b6", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.seed_git_state(tmp_path)

    real_git = findings_migrate.state_sync._git

    def fake_git(args, cwd):
        if args[:1] == ["fetch"]:
            import subprocess
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=1, stdout="",
                stderr="simulated network failure")
        return real_git(args, cwd)

    monkeypatch.setattr(findings_migrate.state_sync, "_git", fake_git)

    with pytest.raises(findings_migrate.MigrationRefused):
        findings_migrate.migrate(tickets, dry_run=True)

    code = findings_migrate.cli(tickets, dry_run=True)
    assert code == 2


def test_real_run_sees_a_straggler_a_peer_pushed_without_a_local_pull(tmp_path, monkeypatch):
    """Same straggler, real-run mode: the re-run meant to confirm zero
    (AC-5) must certify the SHARED state, not a stale local read."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    support.add_ticket(tickets, "KLC-9b2", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    bound = support.seed_git_state(tmp_path)

    old = support.old_independent(1)
    support.push_peer_update(
        bound, tmp_path, "tickets/KLC-9b2/spec-review-findings.json", json.dumps(old))

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "rewritten", row
    new_json = json.loads((tickets / "KLC-9b2" / "spec-review-findings.json").read_text(
        encoding="utf-8"))
    assert new_json[0]["rule_name"] == "infidelity"


def test_a_failed_pull_refuses_loudly_instead_of_a_stale_read(tmp_path, monkeypatch):
    """F-2: a pull failure (network, rebase conflict, a genuine stash-pop
    conflict, …) must refuse the REAL run (`MigrationRefused`, exit 2)
    rather than silently falling through to a stale local read. (Step-8:
    the dry run no longer calls `pull_rebase_preserving` at all — its own
    refusal path is `test_dry_run_refuses_when_the_fetch_itself_fails`
    above.)"""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-9b3", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.seed_git_state(tmp_path)

    def boom(kdir):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(findings_migrate.state_sync, "pull_rebase_preserving", boom)

    with pytest.raises(findings_migrate.MigrationRefused) as exc_info:
        findings_migrate.migrate(tickets)
    assert "could not sync klc-state" in str(exc_info.value)

    code = findings_migrate.cli(tickets)
    assert code == 2
