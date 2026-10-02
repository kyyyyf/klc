"""tests/integration/test_klc154_crash_recovery.py — KLC-154 step-7
(review-fix): an interrupt (KeyboardInterrupt / the BaseException class a
Ctrl-C or SIGKILL-adjacent crash raises) never leaves a ticket silently
reported `unchanged` with the shared state stuck in the old shape.

External review F-1 (HIGH): an interrupt during a ticket's commit/push
leaves the ticket's files rewritten but uncommitted, its audit note
untracked, and every later run reports it `unchanged` with exit 0 while
the remote stays in the old shape. F-4 (MEDIUM): a run interrupted
part-way through a ticket loses the before-hash of files it had already
rewritten, and can leave a stray `.tmp`. F-9 (LOW, code-review-adjacent):
the per-ticket commit must never sweep an unrelated uncommitted file into
the migration's own commit.

Fixed by: `_apply`'s own restore on ANY `BaseException` (not only
`Exception`), a `pending`-before-`complete` audit-note write (so the
before-hash of an already-rewritten file is never lost), and
`_needs_attention` (checked for every ticket, in either mode, BEFORE the
ordinary unchanged/would-rewrite/rewritten classification): a stray
migration `.tmp`, a dangling `pending` audit entry, or — feature ON — any
uncommitted change under the ticket's subtree in the klc-state worktree.

Step-8 (review round 2 fixes) adds the harder half of F-1 (external
review F-1 = code-review F-1, HIGH): a `KeyboardInterrupt` raised AFTER a
ticket's `klc-state` commit genuinely succeeds, but DURING the push that
follows, leaves a perfectly CLEAN working tree (nothing for the old
`git status` check to see) with the commit sitting only locally, ahead of
its upstream. `_needs_attention` now also runs `git rev-list --count
@{upstream}..HEAD -- tickets/<t>/` and flags a non-zero count. It also
closes code-review F-2 (a failed `git status`/`rev-list` must fail CLOSED,
never read as "nothing to worry about") and adds the F-4 fix: `_apply`
appends a change to its restore-candidate list BEFORE calling
`_write_bytes` for it, not after, so an interrupt landing right after a
successful `tmp.replace` can no longer lose that file's restore.

Step-9 (review round 3 fixes) closes the two gaps step-8's own restore
left open. External review F-2 (LOW): step-8's restore walked EVERY
change in the plan, including one the forward loop never reached because
an earlier change's write raised first — restoring it anyway could
clobber something else that had written to that same file in the
meantime. `_apply` now restores only the changes its forward loop
actually started (appended to `started` immediately before each one's own
`_write_bytes` call), never the whole plan. External review F-1 (MEDIUM):
step-8 always rolled the audit note back once its best-effort restore
loop finished, even when one of those restores itself failed — erasing
the `pending` entry's before-hash for a half-migrated, feature-OFF ticket
that has no git to fall back on. The restore loop now tracks whether
every restore in it succeeded; the audit note is rolled back only in that
case, and the `pending` entry is otherwise marked `restore_failed` and
left in place so the next run still reports the ticket needs-attention.
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


# --- F-1(a)/F-4: BaseException during the write loop restores already- ----
# --- written files and the audit note, then re-raises ---------------------

def test_keyboard_interrupt_on_the_second_file_restores_the_first(tmp_path, monkeypatch):
    """A `KeyboardInterrupt` raised while writing the SECOND of two
    changed files restores the FIRST file to its original bytes, removes
    the `pending` audit entry it had just written (so the note goes back
    to its pre-run state — here, absent), and re-raises rather than
    swallowing the interrupt."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9a1", {
        "spec-review.md": support.verdict_md(old, []),
        "spec-review-findings.json": json.dumps(old),
    })
    before_md = (tdir / "spec-review.md").read_bytes()
    before_json = (tdir / "spec-review-findings.json").read_bytes()

    real_write = findings_migrate._write_bytes
    calls = {"md": 0}

    def flaky(path, data):
        if path.name == "spec-review.md":
            calls["md"] += 1
            if calls["md"] == 1:
                raise KeyboardInterrupt()
        return real_write(path, data)

    monkeypatch.setattr(findings_migrate, "_write_bytes", flaky)

    with pytest.raises(KeyboardInterrupt):
        findings_migrate.migrate(tickets)

    assert (tdir / "spec-review.md").read_bytes() == before_md
    assert (tdir / "spec-review-findings.json").read_bytes() == before_json
    assert not (tdir / findings_migrate.AUDIT_NOTE).exists()


def test_pending_audit_entry_records_the_before_hash_before_any_write(tmp_path, monkeypatch):
    """F-4: the `pending` entry (with every file's `sha256_before`) exists
    on disk BEFORE the first content file is touched — proven by failing
    on the very FIRST write and finding the pending entry's hash already
    correct for the (still untouched) original file."""
    import hashlib
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9a4", {
        "spec-review-findings.json": json.dumps(old),
    })
    before = (tdir / "spec-review-findings.json").read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()

    real_write = findings_migrate._write_bytes
    seen_pending = {}

    def spy(path, data):
        if path.name == "spec-review-findings.json" and not seen_pending:
            note = json.loads((tdir / findings_migrate.AUDIT_NOTE).read_text(encoding="utf-8"))
            seen_pending["entry"] = note[-1]
            raise KeyboardInterrupt()
        return real_write(path, data)

    monkeypatch.setattr(findings_migrate, "_write_bytes", spy)

    with pytest.raises(KeyboardInterrupt):
        findings_migrate.migrate(tickets)

    entry = seen_pending["entry"]
    assert entry["status"] == "pending"
    assert entry["files"][0]["sha256_before"] == before_hash
    # and the restore afterwards removed the dangling entry entirely
    assert not (tdir / findings_migrate.AUDIT_NOTE).exists()


# --- F-4: a dangling `pending` entry / a stray `.tmp` are needs-attention --

def test_dangling_pending_audit_entry_is_needs_attention(tmp_path, monkeypatch):
    """A SIGKILL right after the pending entry was written (before the
    finalize, before any file write even) leaves exactly this — no Python
    handler ever runs in that scenario, so simulate it directly."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    tdir = support.add_ticket(tickets, "KLC-9a2", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    (tdir / findings_migrate.AUDIT_NOTE).write_text(
        json.dumps([{"at": "2026-01-01T00:00:00Z", "status": "pending",
                     "files": [{"path": "spec-review-findings.json", "old_count": 1,
                               "new_count": 1, "sha256_before": "x", "sha256_after": "y"}]}],
                   indent=2) + "\n", encoding="utf-8")

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "needs-attention", row
    assert "interrupted" in row["reason"] or "unfinished" in row["reason"]
    assert report["needs_attention"] == 1
    # left completely alone: the one-shape file is untouched
    assert json.loads((tdir / "spec-review-findings.json").read_text(encoding="utf-8")) == one_shape


def test_stray_audit_note_tmp_is_needs_attention_even_when_content_already_migrated(
        tmp_path, monkeypatch):
    """F-4: a death inside `_write_bytes` between `tmp.write_bytes` and
    `tmp.replace` leaves `migration-findings-shape.json.tmp`. That is NOT
    self-healing like a findings-file `.tmp` would be, because every
    content file can already be in the new shape (the ticket would
    otherwise be `unchanged` forever with no audit entry at all)."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    tdir = support.add_ticket(tickets, "KLC-9a3", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    (tdir / f"{findings_migrate.AUDIT_NOTE}.tmp").write_text("{}", encoding="utf-8")

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "needs-attention", row
    assert ".tmp" in row["reason"]
    assert report["needs_attention"] == 1


# --- F-1(b)/F-9: real, git-backed reproduction -----------------------------

def test_interrupted_push_is_needs_attention_on_the_next_run(tmp_path, monkeypatch):
    """The real-world reproduction: `_apply` already succeeded (files
    rewritten, audit note finalized) when the commit/push step raises
    `KeyboardInterrupt`. The first `migrate()` call must propagate the
    interrupt (never swallow it); the SECOND call (the next run) must
    report the ticket `needs-attention`, never `unchanged` — the files
    are on disk in the new shape but uncommitted."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9a5", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.seed_git_state(tmp_path)
    klc = tickets.parent

    real_push = findings_migrate.state_sync.commit_and_push_cas_subtree

    def boom_push(*a, **kw):
        raise KeyboardInterrupt()

    findings_migrate.state_sync.commit_and_push_cas_subtree = boom_push
    try:
        with pytest.raises(KeyboardInterrupt):
            findings_migrate.migrate(tickets)
    finally:
        findings_migrate.state_sync.commit_and_push_cas_subtree = real_push

    # the files ARE rewritten on disk ...
    new_json = json.loads((tdir / "spec-review-findings.json").read_text(encoding="utf-8"))
    assert new_json[0]["rule_name"] == "infidelity"
    assert (tdir / findings_migrate.AUDIT_NOTE).is_file()

    # ... but uncommitted in git
    status = support._git(klc, "status", "--porcelain", "--", "tickets/KLC-9a5/")
    assert status.strip()

    second = findings_migrate.migrate(tickets)
    row = second["tickets"][0]
    assert row["status"] == "needs-attention", row
    assert second["needs_attention"] == 1
    assert row["status"] != "unchanged"


def test_unrelated_dirty_file_in_the_ticket_dir_is_never_swept_into_the_commit(
        tmp_path, monkeypatch):
    """F-9: an unrelated uncommitted file sitting in a ticket's directory
    (a live session's in-progress edit, or anything else) must stay
    uncommitted — decided (step-7): the whole ticket is skipped as
    `needs-attention` rather than having the migration's commit stage
    only a hand-picked path list."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9a6", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.seed_git_state(tmp_path)
    klc = tickets.parent
    base_count = support.remote_commit_count(klc)

    scratch = tdir / "scratch-note.txt"
    scratch.write_text("an unrelated in-progress edit\n", encoding="utf-8")

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "needs-attention", row

    # nothing committed for this ticket; the old-shape file is untouched;
    # the scratch file stays exactly as it was, uncommitted
    assert support.remote_commit_count(klc) == base_count
    assert json.loads((tdir / "spec-review-findings.json").read_text(encoding="utf-8")) == old
    assert scratch.read_text(encoding="utf-8") == "an unrelated in-progress edit\n"
    status = support._git(klc, "status", "--porcelain", "--", "tickets/KLC-9a6/scratch-note.txt")
    assert status.strip()


# --- step-8: a commit that genuinely succeeds, interrupted only on push ---

def test_commit_that_succeeds_interrupted_only_on_push_is_needs_attention(tmp_path, monkeypatch):
    """Step-8 (external review F-1 = code-review F-1, HIGH): round-1's F-1
    fix (`test_interrupted_push_is_needs_attention_on_the_next_run` above)
    patches the WHOLE `commit_and_push_cas_subtree`, so no real git commit
    ever happens there — the ticket's files are uncommitted and the old
    `git status` check alone catches it. The harder, real-world case: the
    commit itself SUCCEEDS (only `state_sync._push_with_cas` is patched,
    not its caller) and only the push raises. `state_tx`'s own terminal
    rollback catches `Exception` only, so the `KeyboardInterrupt` here
    leaves a REAL local commit, a perfectly CLEAN working tree, and the
    remote still holding the old shape. `_needs_attention` must catch this
    via `git rev-list --count @{upstream}..HEAD -- tickets/<t>/`, not via
    `git status` (which sees nothing dirty here at all)."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9a8", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.seed_git_state(tmp_path)
    klc = tickets.parent

    def boom_push_with_cas(*a, **kw):
        raise KeyboardInterrupt()

    monkeypatch.setattr(findings_migrate.state_sync, "_push_with_cas", boom_push_with_cas)

    with pytest.raises(KeyboardInterrupt):
        findings_migrate.migrate(tickets)

    # the commit really happened: the ticket's files are migrated, the
    # worktree under this ticket is perfectly CLEAN, and the local HEAD is
    # ahead of its upstream.
    new_json = json.loads((tdir / "spec-review-findings.json").read_text(encoding="utf-8"))
    assert new_json[0]["rule_name"] == "infidelity"
    status = support._git(klc, "status", "--porcelain", "--", "tickets/KLC-9a8/")
    assert status.strip() == ""
    ahead = support._git(
        klc, "rev-list", "--count", "@{upstream}..HEAD", "--", "tickets/KLC-9a8/")
    assert int(ahead.strip()) >= 1

    second = findings_migrate.migrate(tickets)
    row = second["tickets"][0]
    assert row["status"] == "needs-attention", row
    assert "push" in row["reason"].lower()
    assert second["needs_attention"] == 1
    assert row["status"] != "unchanged"

    code = findings_migrate.cli(tickets)
    assert code == 1


# --- step-8: a failed git status/rev-list check fails CLOSED -------------

def test_needs_attention_fails_closed_when_rev_list_check_errors(tmp_path, monkeypatch):
    """Code-review F-2 (step-8): a FAILED `git rev-list` (not just a clean
    0) must never be read as "nothing to worry about"."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-9a9", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.seed_git_state(tmp_path)

    real_git = findings_migrate.state_sync._git

    def fake_git(args, cwd):
        if ("rev-list" in args and "--count" in args
                and any(a.startswith("tickets/") for a in args)):
            import subprocess
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=128, stdout="", stderr="fatal: boom")
        return real_git(args, cwd)

    monkeypatch.setattr(findings_migrate.state_sync, "_git", fake_git)

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "needs-attention", row
    assert "could not check" in row["reason"]


def test_needs_attention_fails_closed_when_git_status_check_errors(tmp_path, monkeypatch):
    """Code-review F-2 (step-8): same fail-closed rule for the plan-aware
    dirty-tree `git status` check (`_dirty_tree_attention`, run once
    `plan_ticket` knows whether the ticket has anything to migrate)."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old = support.old_independent(1)
    support.add_ticket(tickets, "KLC-9aa", {
        "spec-review-findings.json": json.dumps(old),
    })
    support.seed_git_state(tmp_path)

    real_git = findings_migrate.state_sync._git

    def fake_git(args, cwd):
        if ("status" in args and "--porcelain" in args
                and any(a.startswith("tickets/") for a in args)):
            import subprocess
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=128, stdout="", stderr="fatal: boom")
        return real_git(args, cwd)

    monkeypatch.setattr(findings_migrate.state_sync, "_git", fake_git)

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "needs-attention", row
    assert "could not check" in row["reason"]


# --- step-8: an empty plan's unrelated dirt stays unchanged ---------------

def test_empty_plan_ticket_with_unrelated_dirt_stays_unchanged(tmp_path, monkeypatch):
    """External review F-2 (step-8): a ticket with NOTHING to migrate (its
    stored findings are already one-shape) must not be swept into
    `needs-attention` just because an operator session happens to have an
    unrelated in-progress edit sitting in its directory — ordinary
    in-flight work on an otherwise-untouched ticket is not this
    migration's business."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    tdir = support.add_ticket(tickets, "KLC-9ab", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    support.seed_git_state(tmp_path)
    klc = tickets.parent
    base_count = support.remote_commit_count(klc)

    scratch = tdir / "design.md"
    scratch.write_text("work in progress\n", encoding="utf-8")

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "unchanged", row
    assert support.remote_commit_count(klc) == base_count
    assert scratch.read_text(encoding="utf-8") == "work in progress\n"


def test_empty_plan_ticket_with_dirty_migratable_file_is_needs_attention(tmp_path, monkeypatch):
    """External review F-2 (step-8), the other half: even with an EMPTY
    plan, a dirty audit note (or any other migratable findings/verdict
    file) is still a sign of a half-migrated run and must still escalate
    — keeping the whole-ticket `needs-attention` for anything that looks
    like this migration's own leftover, never just "any dirt"."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    tdir = support.add_ticket(tickets, "KLC-9ac", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    support.seed_git_state(tmp_path)

    (tdir / findings_migrate.AUDIT_NOTE).write_text("[]", encoding="utf-8")

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "needs-attention", row


# --- step-8/9: append-before-write means a file whose forward write never --
# --- started is restored as a no-op, never mistaken for a lost restore ----

def test_interrupt_right_after_write_bytes_replaces_the_file_still_restores_it(
        tmp_path, monkeypatch):
    """F-4 (step-8, external review F-4): appending to the restore
    candidate list must happen BEFORE `_write_bytes` is called, not after
    — otherwise an interrupt that lands in the gap between a successful
    `tmp.replace(path)` and an append running AFTER that call would leave
    that file migrated (new bytes) while a restore loop built from such a
    list skips it entirely, silently losing its before-hash even though
    nothing failed structurally. Step-9 narrows the restore loop itself to
    only that append-before-call list (`started`, see `_apply`'s
    docstring) rather than every planned change — this test only needs
    the append-before-write ordering, so it still holds unchanged."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old1 = support.old_independent(1)
    old2 = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9a7", {
        "spec-review-findings.json": json.dumps(old1),
        "test-plan-review-findings.json": json.dumps(old2),
    })
    before_a = (tdir / "spec-review-findings.json").read_bytes()
    before_b = (tdir / "test-plan-review-findings.json").read_bytes()

    real_write = findings_migrate._write_bytes

    def flaky(path, data):
        real_write(path, data)
        if path.name == "test-plan-review-findings.json":
            raise KeyboardInterrupt()

    monkeypatch.setattr(findings_migrate, "_write_bytes", flaky)

    with pytest.raises(KeyboardInterrupt):
        findings_migrate.migrate(tickets)

    assert (tdir / "spec-review-findings.json").read_bytes() == before_a
    assert (tdir / "test-plan-review-findings.json").read_bytes() == before_b


# --- step-8: the F-5 recovery recipe is named in the reason --------------

def test_dangling_pending_entry_reason_names_the_recovery_recipe(tmp_path, monkeypatch):
    """External review F-5 (step-8): the reason string for a dangling
    `pending` audit entry must name HOW to recover, not just that
    something is wrong — comparing each listed file's sha256 against
    sha256_before/sha256_after, restoring a mismatch from the tar backup
    (or marking the entry complete once everything already matches), then
    re-running."""
    tickets = support.make_project(tmp_path, monkeypatch)
    one_shape = [{"id": "F-1", "rule_name": "infidelity", "severity": "HIGH",
                 "file": "spec.md", "line": None, "title": "t", "body": "b", "fix": None}]
    tdir = support.add_ticket(tickets, "KLC-9ad", {
        "spec-review-findings.json": json.dumps(one_shape),
    })
    (tdir / findings_migrate.AUDIT_NOTE).write_text(
        json.dumps([{"at": "2026-01-01T00:00:00Z", "status": "pending",
                     "files": [{"path": "spec-review-findings.json", "old_count": 1,
                               "new_count": 1, "sha256_before": "x", "sha256_after": "y"}]}],
                   indent=2) + "\n", encoding="utf-8")

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "needs-attention", row
    assert "sha256_before" in row["reason"]
    assert "sha256_after" in row["reason"]
    assert "tar backup" in row["reason"]
    assert "complete" in row["reason"]
    assert "re-run" in row["reason"]


# --- step-9: a restore that itself fails must never erase the pending -----
# --- entry (external review F-1, round 3) ----------------------------------

def test_restore_failure_keeps_the_pending_entry_and_the_before_hash(tmp_path, monkeypatch):
    """External review F-1 (round 3, MEDIUM): step-8's restore loop wraps
    every restore attempt in `except BaseException: pass` but then always
    rolls the audit note back to its PRIOR state regardless — so a
    feature-OFF ticket where the restore of an already-rewritten file
    ALSO fails (e.g. the disk is still full) loses the one piece of
    evidence an operator needs to recover it: the `pending` entry with
    that file's `sha256_before`. The pending entry must survive untouched
    whenever any restore failed, so the NEXT run reports the ticket
    needs-attention instead of silently reading it as clean."""
    import hashlib
    tickets = support.make_project(tmp_path, monkeypatch)
    old1 = support.old_independent(1)
    old2 = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9ae", {
        "spec-review-findings.json": json.dumps(old1),
        "test-plan-review-findings.json": json.dumps(old2),
    })
    before_a = (tdir / "spec-review-findings.json").read_bytes()
    before_a_hash = hashlib.sha256(before_a).hexdigest()

    real_write = findings_migrate._write_bytes
    calls = {}

    def flaky(path, data):
        calls[path.name] = calls.get(path.name, 0) + 1
        # the forward write of the SECOND file (test-plan) fails outright ...
        if path.name == "test-plan-review-findings.json" and calls[path.name] == 1:
            raise OSError("disk full (forward write)")
        # ... and restoring the FIRST file (spec), which DID get written,
        # fails too (the disk is still full).
        if path.name == "spec-review-findings.json" and calls[path.name] == 2:
            raise OSError("disk full (restore)")
        return real_write(path, data)

    monkeypatch.setattr(findings_migrate, "_write_bytes", flaky)

    first = findings_migrate.migrate(tickets)
    row = first["tickets"][0]
    assert row["status"] == "skipped", row

    note = json.loads((tdir / findings_migrate.AUDIT_NOTE).read_text(encoding="utf-8"))
    assert note[-1]["status"] == "pending"
    assert note[-1]["files"][0]["sha256_before"] == before_a_hash
    assert note[-1].get("restore_failed") is True

    monkeypatch.setattr(findings_migrate, "_write_bytes", real_write)
    second = findings_migrate.migrate(tickets)
    row2 = second["tickets"][0]
    assert row2["status"] == "needs-attention", row2
    assert "restore" in row2["reason"]
    assert "ALSO failed" in row2["reason"]


# --- step-9: the restore never rewrites a file the forward loop never -----
# --- reached (external review F-2, round 3) --------------------------------

def test_restore_never_rewrites_a_file_the_forward_loop_never_reached(tmp_path, monkeypatch):
    """External review F-2 (round 3, LOW): step-8's restore loop walked
    EVERY change in `plan.changes`, including one the forward loop never
    even got to because an EARLIER change's write raised first. Restoring
    such a change is not a no-op when something else wrote to that same
    file in the meantime (a non-locking reader, or — as simulated here —
    a concurrent edit landing in the window between the plan being taken
    and `_apply` reaching that file): the restore loop force-rewrote it
    with the file's OLD bytes anyway, silently clobbering the edit. The
    restore must only ever touch a change already appended to `started`
    (immediately before its own `_write_bytes` call), never one the
    forward loop stopped short of."""
    tickets = support.make_project(tmp_path, monkeypatch)
    old1 = support.old_independent(1)
    old2 = support.old_independent(1)
    old3 = support.old_independent(1)
    tdir = support.add_ticket(tickets, "KLC-9af", {
        "spec-review-findings.json": json.dumps(old1),
        "test-plan-review-findings.json": json.dumps(old2),
        "impl-plan-review-findings.json": json.dumps(old3),
    })

    real_write = findings_migrate._write_bytes
    edited = b'{"edited": true}\n'
    calls = {"tp": 0}

    def flaky(path, data):
        if path.name == "test-plan-review-findings.json":
            calls["tp"] += 1
            if calls["tp"] == 1:
                # a concurrent edit lands on the THIRD file while the
                # SECOND file's write is in flight — the forward loop
                # never reaches the third file at all, because this
                # raise (on the FORWARD call only) stops it here.
                (tdir / "impl-plan-review-findings.json").write_bytes(edited)
                raise OSError("boom")
        return real_write(path, data)

    monkeypatch.setattr(findings_migrate, "_write_bytes", flaky)

    report = findings_migrate.migrate(tickets)
    row = report["tickets"][0]
    assert row["status"] == "skipped", row

    assert (tdir / "impl-plan-review-findings.json").read_bytes() == edited
