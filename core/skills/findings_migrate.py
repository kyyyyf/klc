#!/usr/bin/env python3
"""findings_migrate.py — the one-off migration of stored findings files to
the one Finding shape (KLC-154).

Since KLC-127 every reader (`findings.py pool`, the ack parser of the four
independent reviews) reads only the one Finding shape; an old-shape file is
skipped with a note "run the KLC-154 migration" (`handback._read_stored_findings`).
This module is the migration engine: `plan_ticket` visits one ticket
directory, maps every old-shape findings JSON file and the verdict block of
each independent kind's `.md`, checks every mapped list/block in STORED mode
(`handback.validate_findings`) and cross-checks the `.md`/JSON pair (AC-9),
all in memory, BEFORE any write. `migrate` walks every ticket directory,
applying a ticket's plan only when it has changes; a ticket whose plan fails
is listed `failed` with its reason and left byte-identical, and one
malformed ticket never stops the batch (AC-6). A changed ticket is written
through `_migrate_one` (one `acquire_lock` + one `state_tx`, re-planned on
the pulled state, step-2) unless `dry_run` is given (step-5), in which case
nothing is locked, transacted or written. `cli` is `handback.py migrate`'s
whole behaviour: `_check_preconditions` refuses an unsuitable root or an
outdated `spec_review` before the first ticket is visited (step-5, AC-11).

Step-7 (review-fix) hardens the batch against an interrupt and a stale
local read: `migrate` pulls `klc-state` once up front when the multi-user
feature is ON (`_sync_state_or_refuse`, so a peer's straggler push is seen
before the pre-plan decides anything) and, per ticket, checks for a sign
of a half-migrated run BEFORE deciding `unchanged` (`_needs_attention`: a
stray migration `.tmp`, a dangling `pending` audit entry, or — feature ON —
any uncommitted change under the ticket's subtree) — such a ticket is
listed `needs-attention` and left alone, never `unchanged`, never swept
into this run's own commit. `_apply` now writes a `pending` audit entry
BEFORE any file (so the before-hash of a file is never lost to a
mid-write crash) and restores on ANY `BaseException` (a `KeyboardInterrupt`
included), not only `Exception`.

Step-8 (review round 2 fixes) closes the gap left by a `KeyboardInterrupt`
that lands AFTER a real `klc-state` commit but DURING the push that
follows: `state_tx`'s own rollback catches only `Exception`, so the commit
stays local, the working tree is perfectly clean, and the step-7
`git status` check alone saw nothing wrong. `_needs_attention` now also
runs `git rev-list --count @{upstream}..HEAD -- tickets/<t>/` (feature ON)
and flags a non-zero count — a non-zero `returncode` from THAT check, or
from the dirty-tree `git status` check, fails CLOSED (`needs-attention`),
never silently treated as clean. The dirty-tree check itself is now
plan-aware (`_dirty_tree_attention`, run once `plan_ticket` has already
decided whether the ticket has anything to migrate): a ticket with planned
changes still escalates on ANY dirt (unchanged would sweep unrelated work
into this run's own commit), but a ticket whose plan is EMPTY escalates
only when the dirty paths include the audit note or a migratable findings/
verdict file — ordinary in-progress work on an otherwise-untouched ticket
is not this migration's business. In dry-run mode (feature ON) `migrate`
no longer pulls/stashes/resets the `klc-state` worktree at all (AC-1): it
only fetches the upstream and refuses (`MigrationRefused`, exit 2) when the
local branch is behind it, or when the fetch itself fails
(`_check_dry_run_not_stale`); the real run keeps the full
`pull_rebase_preserving` (`_sync_state_or_refuse`). `_apply`'s restore loop
no longer restores every file in the plan unconditionally; it restores
only the changes a `started` list already recorded (appended immediately
before each one's own `_write_bytes` call).

Step-9 (review round 3 fixes) closes the two gaps step-8's restore left
open. First (external review F-2): walking the WHOLE plan during a
restore — step-8's own design — meant a change the forward loop never
even reached (because an earlier one's write raised first) still got
force-rewritten with its `old` bytes, silently clobbering anything else
that had written to that same file in the meantime. `_apply` now builds
`started` by appending each change right before attempting it, and
restores only `reversed(started)` — the identical append-before-call
ordering step-8's F-4 fix already used for a different reason, now also
closing this one. Second (external review F-1): step-8's restore always
rolled the audit note back to its pre-run state once the best-effort
restore loop finished, even when one of those restores itself failed —
so a half-migrated, feature-OFF ticket (no git to fall back on) lost the
one thing that would let an operator recover it: the `pending` entry
carrying the failed file's `sha256_before`. The restore loop now tracks
whether every restore in it succeeded; the audit note is rolled back only
in that case, and otherwise the `pending` entry is marked
`restore_failed` and left in place (`_mark_restore_failed`) so the next
run's `_needs_attention` still reports it, never `unchanged`.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings  # noqa: E402
import handback  # noqa: E402
import spec_review  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402
from _paths import klc_dir, klc_tickets_dir  # noqa: E402


class MigrationRefused(Exception):
    """The migration refuses to run at all (AC-11): `--tickets-root` is not
    this project's tickets directory, the imported `spec_review` does not
    have the one-shape parser, or — when the klc-state feature is ON — the
    up-front klc-state sync fails (the real run's pull, or the dry run's
    fetch / behind-upstream check, step-8)."""


_PROBE = ('```json\n{"findings": [{"id": "F-1", "rule_name": "infidelity", '
         '"severity": "HIGH", "file": "spec.md", "line": null, "title": "t", '
         '"body": "b", "fix": null}], "decisions_to_confirm": []}\n```\n')


def one_shape_parser_present(module) -> bool:
    """True iff *module* has a `parse_review` that returns a one-shape
    `findings.Finding` for the canned probe verdict above — any failure
    (missing attribute, old shape, wrong type) means "not the one-shape
    parser"."""
    try:
        first = module.parse_review(_PROBE).findings[0]
    except Exception:  # noqa: BLE001 - any failure means "not the one-shape parser"
        return False
    return isinstance(first, findings.Finding) and first.rule_name == "infidelity"


def _check_preconditions(tickets_root) -> None:
    root = Path(tickets_root)
    if not root.is_dir() or root.resolve() != klc_tickets_dir().resolve():
        raise MigrationRefused(
            f"--tickets-root {tickets_root} is not this project's "
            f"tickets directory ({klc_tickets_dir()})")
    if not one_shape_parser_present(spec_review):
        raise MigrationRefused(
            "the imported spec_review.parse_review does not return a "
            "one-shape Finding; pull main with KLC-127 first")

AUDIT_NOTE = "migration-findings-shape.json"

# --- old-shape vocabularies (pre-KLC-127) -----------------------------------

_OLD_INDEPENDENT = frozenset({"id", "category", "severity", "detail", "ref", "suggested_fix"})
_OLD_IN_CLIENT = frozenset({"severity", "file", "line", "title", "body", "fix", "ac"})

_INDEPENDENT = ("spec", "test-plan", "impl-plan", "drift")


class MappingError(ValueError):
    """An old-shape record carries a key the mapping does not recognise
    (D-006) — the ticket's plan fails before any write."""


class PlanError(Exception):
    """A ticket's plan cannot be trusted: unreadable/invalid JSON, a record
    that fails the AC-8 stored-mode check after mapping, or an AC-9
    cross-check disagreement. The ticket is listed `failed` and left
    byte-identical."""


@dataclass
class FileChange:
    """One file's rewrite, planned in memory before any write."""
    path: str
    old: bytes
    new: bytes
    old_count: int
    new_count: int

    def entry(self) -> dict:
        import hashlib
        return {
            "path": self.path,
            "old_count": self.old_count,
            "new_count": self.new_count,
            "sha256_before": hashlib.sha256(self.old).hexdigest(),
            "sha256_after": hashlib.sha256(self.new).hexdigest(),
        }


@dataclass
class TicketPlan:
    """One ticket's read-only migration plan: the changes it would make
    (empty when the ticket needs no change), or a `reason` when the plan
    itself failed (the ticket is then left byte-identical)."""
    ticket: str
    changes: list = field(default_factory=list)
    reason: str = ""


def is_old(rec) -> bool:
    """True iff *rec* is in one of the two pre-KLC-127 shapes — mirrors
    `findings.check_findings`'s own two shape-detection conditions, without
    the rest of its validation."""
    return isinstance(rec, dict) and (
        any(k in rec for k in ("category", "detail", "suggested_fix"))
        or not rec.get("id") or "rule_name" not in rec)


_REF_LOC_RE = re.compile(r"^\s*([\w./-]+\.[A-Za-z0-9]+):(\d+)\s*$")


_SENTENCE_SPLIT_RE = re.compile(r"(?<!\.\.)(?<=[.!?])\s")


def _title(detail: str) -> str:
    """The first sentence of *detail*, cut at the last word boundary at or
    before 120 characters (D-1); falls back to a hard cut at 120 when the
    first 120 characters hold no space. The full text always stays in
    `body` — nothing here is lost, only the title is shortened.

    Step-7 (external review F-7): a literal ellipsis ('...') is never
    read as a sentence end (the split's lookbehind excludes a `.` that is
    itself preceded by two more dots), and whenever the returned title is
    SHORTER than the untruncated detail — whether cut by the sentence
    split or by the 120-character word-boundary cut — a single '…'
    (U+2026) is appended so a reader never sees a title that reads as
    complete but means something else."""
    flat = " ".join(detail.split())
    parts = _SENTENCE_SPLIT_RE.split(flat, maxsplit=1)
    first = parts[0]
    cut_by_sentence = len(parts) > 1
    if len(first) <= 120:
        return first + ("…" if cut_by_sentence else "")
    cut = first[:121].rfind(" ")
    short = (first[:cut] if cut > 0 else first[:120]).rstrip()
    return short + "…"


def map_finding(rec: dict, kind: str, position: int) -> dict:
    """Map one raw finding dict to the one Finding shape. A record already
    in the one shape is returned unchanged (D-002). The rules of the
    spec's Data shapes section: vocabulary category or
    `legacy-unclassified` (with the old category kept as a
    `[legacy category: X]` prefix on the body), upper-cased severity,
    `detail` as `body`, the first sentence (word-boundary cut at 120
    characters) as `title`, a `ref` of the form `path:N` with N >= 1
    supplying `file`/`line` (else the kind's artefact with a null `line`),
    in-client `F-n` id by position, and a non-positive `line` set to
    null."""
    if not is_old(rec):
        return rec
    if any(k in rec for k in ("category", "detail", "suggested_fix")):
        extra = set(rec) - _OLD_INDEPENDENT
        if extra:
            raise MappingError(f"unknown key(s) {sorted(extra)} on an old independent finding")
        detail = str(rec.get("detail", "")).strip()
        cat = rec.get("category", "")
        rule_names = handback.KINDS[kind].rule_names or ()
        known = cat in rule_names
        ref = str(rec.get("ref", ""))
        loc = _REF_LOC_RE.match(ref)
        has_loc = bool(loc) and int(loc.group(2)) >= 1
        return {
            "id": rec.get("id") or f"F-{position}",
            "rule_name": cat if known else findings.LEGACY_RULE_NAME,
            "severity": str(rec.get("severity", "")).upper(),
            "file": loc.group(1) if has_loc else handback.KINDS[kind].artefact,
            "line": int(loc.group(2)) if has_loc else None,
            "title": _title(detail),
            "body": detail if known else f"[legacy category: {cat}] {detail}",
            "fix": rec.get("suggested_fix") or None,
            "ref": ref,
        }
    extra = set(rec) - _OLD_IN_CLIENT
    if extra:
        raise MappingError(f"unknown key(s) {sorted(extra)} on an old in-client finding")
    line = rec.get("line")
    return {
        **rec,
        "id": f"F-{position}",
        "rule_name": findings.LEGACY_RULE_NAME,
        "severity": str(rec.get("severity", "")).upper(),
        "line": line if type(line) is int and line > 0 else None,
    }


def map_findings(items: list, kind: str, *, stamp: bool = False) -> list:
    """Map every record of *items* for *kind*. With `stamp=True` (JSON
    files only), each mapped record is round-tripped through
    `findings.Finding` with `reviewer`/`kind` set to *kind* — but ONLY when
    not already present (a present value is kept)."""
    mapped = [map_finding(rec, kind, i) for i, rec in enumerate(items, start=1)]
    if not stamp:
        return mapped
    out = []
    for m in mapped:
        d = {**m, "reviewer": m.get("reviewer") or kind, "kind": m.get("kind") or kind}
        out.append(findings.Finding.from_dict(d).to_dict())
    return out


def _verdict_span(text: str):
    """`spec_review._extract_json`'s own selection rule, with the span
    (D-003): the LAST fenced JSON candidate that parses is THE verdict
    block, whether or not it carries `findings`/`decisions_to_confirm` — a
    valid-but-wrong-shape last block means "no verdict here", never a
    fall-back search of an earlier block."""
    spans = [m.span(1) for m in spec_review._JSON_FENCE_RE.finditer(text)]
    stripped = text.strip()
    if not spans and stripped.startswith("{") and stripped.endswith("}"):
        start = text.index(stripped)
        spans = [(start, start + len(stripped))]
    for a, b in reversed(spans):
        try:
            doc = json.loads(text[a:b])
        except ValueError:
            continue
        if isinstance(doc, dict):
            has_verdict = "findings" in doc or "decisions_to_confirm" in doc
            return (a, b, doc) if has_verdict else None
    return None


def rewrite_md_block(text: str, kind: str):
    """Rewrite the verdict block's `findings` in place, keeping every byte
    outside the JSON span and the original layout style (D-004). Returns
    `(new_text, old_findings, new_findings)`, or `None` when there is no
    old-shape verdict to migrate (no verdict block at all, or its findings
    are already in the one shape)."""
    span = _verdict_span(text)
    if span is None:
        return None
    a, b, doc = span
    old = list(doc.get("findings") or [])
    if not any(is_old(r) for r in old):
        return None
    new_findings = map_findings(old, kind)
    new_doc = {k: (new_findings if k == "findings" else v) for k, v in doc.items()}
    indent = None if "\n" not in text[a:b] else 2
    js = json.dumps(new_doc, ensure_ascii=False, indent=indent)
    if "\r\n" in text[a:b]:
        js = js.replace("\n", "\r\n")
    return text[:a] + js + text[b:], old, new_doc["findings"]


def _read_list(tdir: Path, rel: str):
    """Read *rel* under *tdir* as a JSON list, or `None` when it is absent.
    A read/parse/shape error becomes `PlanError`, naming the file. A
    symlink at *rel* is refused outright (code-review F-1, checked BEFORE
    `is_file()`, which would otherwise follow it): the atomic writer's
    `tmp.replace(path)` would silently turn the symlink into a plain file
    holding the new content, leaving its real target untouched elsewhere
    and the symlink itself gone."""
    path = tdir / rel
    if path.is_symlink():
        raise PlanError(f"{rel}: refuses to migrate a symlinked file")
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PlanError(f"{rel}: unreadable ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanError(f"{rel}: invalid JSON ({exc})") from exc
    if not isinstance(data, list):
        raise PlanError(f"{rel}: not a JSON list")
    return data


def _checked(kind: str, rel: str, old_items, mapped) -> None:
    """AC-8: the mapped list/block must pass `handback.validate_findings`
    (stored mode) BEFORE it is ever written."""
    errors = handback.validate_findings(kind, mapped)
    if errors:
        raise PlanError(f"{rel}: AC-8 check failed after mapping ({'; '.join(errors[:3])})")


def _json_bytes(records: list) -> bytes:
    return (json.dumps(records, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def plan_ticket(tdir: Path) -> TicketPlan:
    """One ticket's read-only migration plan (see module docstring)."""
    plan = TicketPlan(tdir.name)
    try:
        stored: dict = {}
        for kind, spec in handback.KINDS.items():
            rel = spec.stored or f"{kind}-review-findings.json"
            items = _read_list(tdir, rel)
            if items is None:
                continue
            stored[kind] = items
            if any(is_old(r) for r in items):
                records = map_findings(items, kind, stamp=True)
                _checked(kind, rel, items, records)
                stored[kind] = records
                plan.changes.append(FileChange(
                    rel, (tdir / rel).read_bytes(), _json_bytes(records),
                    len(items), len(records)))
        for kind in _INDEPENDENT:
            binding = handback.KINDS[kind].binding
            md = tdir / binding.output_file
            if md.is_symlink():
                raise PlanError(f"{binding.output_file}: refuses to migrate a symlinked file")
            if not md.is_file():
                continue
            raw = md.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PlanError(f"{binding.output_file}: unreadable ({exc})") from exc
            res = rewrite_md_block(text, kind)
            if res is not None:
                text, old, new = res
                _checked(kind, binding.output_file, old, new)
                plan.changes.append(FileChange(
                    binding.output_file, raw, text.encode("utf-8"), len(old), len(new)))
            if kind in stored:
                stored_rel = handback.KINDS[kind].stored or f"{kind}-review-findings.json"
                derived = spec_review.record_findings(
                    spec_review.parse_review(text, binding), None, binding)
                if derived != stored[kind]:
                    raise PlanError(
                        f"AC-9 cross-check: {binding.output_file} and {stored_rel} "
                        f"disagree for kind {kind!r}")
        if plan.changes:
            note = tdir / AUDIT_NOTE
            if note.is_file():
                try:
                    json.loads(note.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise PlanError(f"{AUDIT_NOTE}: unreadable ({exc})") from exc
    except (PlanError, MappingError, OSError, UnicodeDecodeError) as exc:
        return TicketPlan(tdir.name, reason=str(exc))
    return plan


def _write_bytes(path: Path, data: bytes) -> None:
    """Atomic write: a temporary file plus rename, the temp file removed in
    a `finally` (so a failed rename never leaves a stray `.tmp`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_audit(tdir: Path) -> list:
    path = tdir / AUDIT_NOTE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _write_audit(tdir: Path, runs: list) -> None:
    """Write *runs* back, or remove the note entirely when *runs* is now
    empty (a rolled-back first-ever entry leaves no note at all, matching
    the pre-run state byte-for-byte)."""
    path = tdir / AUDIT_NOTE
    if not runs:
        if path.is_file():
            path.unlink()
        return
    _write_bytes(path, (json.dumps(runs, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _append_pending_audit(tdir: Path, plan: TicketPlan) -> list:
    """Step-7 (external review F-4): append a `status: "pending"` run
    entry FIRST, BEFORE any content file is written — every file's
    before/after hash is already known from the in-memory plan, so this
    closes the one real gap: a crash between two file writes used to lose
    the before-hash of the file(s) already rewritten, because the old
    `_append_audit` ran LAST. Returns the prior runs list so a caller that
    has to unwind can restore the note to exactly its pre-run state."""
    runs = _read_audit(tdir)
    prior = list(runs)
    runs.append({"at": _now(), "status": "pending", "files": [c.entry() for c in plan.changes]})
    _write_audit(tdir, runs)
    return prior


def _finalize_audit(tdir: Path) -> None:
    """Flip the last (this run's) entry from `pending` to `complete` once
    every file has been written — a `pending` entry still sitting there
    on a later read is itself evidence of an interrupted run
    (`_needs_attention`)."""
    runs = _read_audit(tdir)
    if runs and isinstance(runs[-1], dict) and runs[-1].get("status") == "pending":
        runs[-1] = {**runs[-1], "status": "complete"}
        _write_audit(tdir, runs)


def _mark_restore_failed(tdir: Path) -> None:
    """Step-9 (external review F-1, round 3): called from `_apply`'s
    failure path only when at least one restore attempt itself failed.
    The `pending` entry must NEVER be reverted in that case — reverting it
    would erase the one piece of evidence (the file's `sha256_before`) an
    operator needs to recover a ticket where a file is still sitting in
    the NEW shape because its restore failed too. Stamping the entry
    `restore_failed: true` in place (rather than just leaving it exactly
    as `_append_pending_audit` wrote it) is purely informational: it lets
    `_needs_attention` give a more precise reason than the generic
    "a prior migration was interrupted" wording. Best-effort, like every
    other audit-note write in this failure path: a failure here is
    swallowed by the caller."""
    runs = _read_audit(tdir)
    if runs and isinstance(runs[-1], dict) and runs[-1].get("status") == "pending":
        runs[-1] = {**runs[-1], "restore_failed": True}
        _write_audit(tdir, runs)


def _apply(tdir: Path, plan: TicketPlan) -> None:
    """Write the `pending` audit entry, then every changed file, then
    finalize the entry. ANY failure — including a `BaseException` such as
    `KeyboardInterrupt` (step-7, external review F-1: the real-world
    reproduction is an interrupt that lands here or in the push that
    follows) — restores every file the forward loop actually started
    writing, then re-raises. This restore holds even with the multi-user
    feature OFF (`state_tx` is then a pure pass-through with no git-level
    rollback, D-007's `test_feature_off_*`).

    Step-9 (external review F-1/F-2, round 3) replaces step-8's restore
    design, which had two separate problems:

    - F-2: step-8 walked EVERY change in *plan.changes* during the
      restore, including one the forward loop never even reached because
      an earlier change's write raised first. Restoring such a change is
      NOT a harmless no-op in general — something else could have written
      to that same file in the window between the plan being taken and
      `_apply` reaching it, and the old restore loop force-rewrote it
      with the plan's `old` bytes anyway, silently clobbering that edit.
      The forward loop below now appends each change to `started`
      immediately BEFORE calling `_write_bytes` for it (closing the same
      gap step-8's F-4 fix closed, between a successful `tmp.replace` and
      a bookkeeping append that used to run only afterward) — so `started`
      is exactly the set of changes the forward loop actually attempted,
      and the restore walks `reversed(started)`, never the full plan.
      Each restore is still wrapped in its own `try/except BaseException`
      so one change's restore failing never blocks the others.
    - F-1: step-8 always rolled the audit note back to *prior_runs* once
      the best-effort restore loop finished, even when one of those
      restores itself failed — so a half-migrated, feature-OFF ticket
      (no git to fall back on) lost the only evidence of that: the
      `pending` entry carrying the failed file's `sha256_before`. The
      restore loop now tracks whether EVERY restore attempt in it
      succeeded; the audit note is rolled back to *prior_runs* only in
      that case. If any restore failed, the `pending` entry is instead
      marked `restore_failed` (`_mark_restore_failed`) and left in place,
      so the NEXT run's `_needs_attention` still reports it — never
      `unchanged`, exactly as a plain interrupted run already does.

    In both cases the exception that propagates out of `_apply` is always
    the ORIGINAL one from the forward loop, never a restore-time one."""
    prior_runs = _append_pending_audit(tdir, plan)
    started: list = []
    try:
        for change in plan.changes:
            started.append(change)
            _write_bytes(tdir / change.path, change.new)
        _finalize_audit(tdir)
    except BaseException:
        restore_failed = False
        for change in reversed(started):
            try:
                _write_bytes(tdir / change.path, change.old)
            except BaseException:
                restore_failed = True  # best-effort: never let one restore block the rest
        try:
            if restore_failed:
                _mark_restore_failed(tdir)
            else:
                _write_audit(tdir, prior_runs)
        except BaseException:
            pass
        raise


class _PlanFailed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _NoChange(Exception):
    pass


def _row(ticket: str, status: str, changes=None, reason: str = "") -> dict:
    return {
        "ticket": ticket, "status": status, "reason": reason,
        "files": [c.entry() for c in (changes or [])],
    }


def _report(rows: list, *, dry_run: bool = False) -> dict:
    out = {
        "tickets": rows,
        "files_changed": sum(len(r["files"]) for r in rows if r["status"] == "rewritten"),
        "failed": sum(1 for r in rows if r["status"] == "failed"),
        "skipped": sum(1 for r in rows if r["status"] == "skipped"),
        "needs_attention": sum(1 for r in rows if r["status"] == "needs-attention"),
    }
    if dry_run:
        # external review F-3: `files_changed` only ever counts an ACTUAL
        # rewrite, so a dry run (which never rewrites anything) always
        # printed/returned 0 even when hundreds of files would change.
        # Report the would-rewrite totals separately, dry-run only.
        would = [r for r in rows if r["status"] == "would-rewrite"]
        out["would_change_tickets"] = len(would)
        out["would_change_files"] = sum(len(r["files"]) for r in would)
    return out


def _migrate_one(tdir: Path) -> dict:
    """One ticket's write, inside its own `acquire_lock` + `state_tx`
    (AC-2, AC-10): re-plans on the pulled state (so a racing writer's
    changes are never acted on stale), applies only when the re-plan still
    has changes, and maps every `state_sync`/`LockedError`/bare-exception
    failure to one `skipped` row — mirrors `scope_fix._migrate_one`'s own
    exception ladder."""
    ticket = tdir.name
    try:
        with acquire_lock(ticket):
            with state_tx.state_tx(ticket, f"KLC-154 migrate findings shape {ticket}"):
                plan = plan_ticket(tdir)
                if plan.reason:
                    raise _PlanFailed(plan.reason)
                if not plan.changes:
                    raise _NoChange()
                _apply(tdir, plan)
                return _row(ticket, "rewritten", plan.changes)
    except _PlanFailed as exc:
        return _row(ticket, "failed", reason=exc.reason)
    except (_NoChange, state_sync.NothingToCommitError):
        return _row(ticket, "unchanged")
    except state_sync.StaleStateError:
        return _row(ticket, "skipped", reason="stale - retry")
    except (state_sync.StashConflictError, state_sync.StateConflictError,
            state_sync.RebaseConflictError, state_sync.RetryExhaustedError,
            state_sync.ConfigError) as exc:
        return _row(ticket, "skipped", reason=f"{type(exc).__name__}: {exc}")
    except LockedError as exc:
        return _row(ticket, "skipped", reason=f"locked: {exc}")
    except Exception as exc:  # noqa: BLE001 - scope_fix._migrate_one parity
        return _row(ticket, "skipped", reason=f"write failed: {exc}")


def _migratable_rels() -> frozenset:
    """Step-8 (external review F-2): every relative path this migration can
    EVER rewrite for some ticket, plus the audit note itself — the set a
    dirty path is checked against before an EMPTY plan's unrelated dirt is
    allowed to escalate a ticket to `needs-attention` (`_dirty_tree_attention`
    below). Derived from `handback.KINDS` rather than hard-coded, so it can
    never drift from the real candidate set `plan_ticket` itself reads."""
    rels = {AUDIT_NOTE}
    for kind, spec in handback.KINDS.items():
        rels.add(spec.stored or f"{kind}-review-findings.json")
        if spec.binding is not None:
            rels.add(spec.binding.output_file)
    return frozenset(rels)


def _dirty_rel_paths(porcelain: str, ticket: str) -> list:
    """Every path `git status --porcelain -- tickets/<ticket>/` lists,
    relative to the ticket directory (a rename's line reports both the old
    and new path; only the new one is kept, matching where the content now
    lives)."""
    prefix = f"tickets/{ticket}/"
    out = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        path_part = line[3:] if len(line) > 3 else line.strip()
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        path_part = path_part.strip().strip('"')
        if path_part.startswith(prefix):
            out.append(path_part[len(prefix):])
    return out


def _dirt_touches_migratable(porcelain: str, ticket: str) -> bool:
    migratable = _migratable_rels()
    return any(rel in migratable for rel in _dirty_rel_paths(porcelain, ticket))


def _needs_attention(tdir: Path, kdir: Path, feature_on: bool) -> str | None:
    """Step-7 (external review F-1/F-4/F-9), extended by step-8 (external
    F-1 = code-review F-1): a reason string when *tdir* shows a sign of a
    half-migrated run — checked for EVERY ticket, in EITHER mode, BEFORE
    `plan_ticket` even runs, so a half-migrated ticket is never again
    reported `unchanged`. These checks need no plan (see
    `_dirty_tree_attention` below for the one that does):

    1. a stray migration `.tmp` sibling — a crash between
       `tmp.write_bytes` and `tmp.replace` in `_write_bytes`; usually
       self-healing for a findings file (which is then still old-shape
       and gets rewritten), never self-healing for the audit note's own
       `.tmp` (every content file can already be in the new shape).
    2. a dangling `status: "pending"` entry in the audit note — the only
       signal left on a feature-OFF project (no git to fall back on),
       and the one a SIGKILL right after `_append_pending_audit` leaves
       behind (no Python handler ever runs to restore it). The reason
       names the recovery recipe (step-8, external review F-5): compare
       each listed file's sha256 against sha256_before/sha256_after,
       restore a mismatch from the tar backup (or mark the entry
       complete once every file already matches sha256_after), then
       re-run.
    3. feature ON only: a LOCAL `klc-state` commit touching this ticket
       that is not yet pushed to its upstream (`git rev-list --count
       @{upstream}..HEAD -- tickets/<t>/` > 0) — the harder half of F-1:
       `state_tx`'s terminal rollback catches only `Exception`, so a
       `KeyboardInterrupt` raised DURING the push (after the commit
       itself already succeeded) leaves a perfectly clean working tree
       with no `git status` dirt at all, visible only as a commit ahead
       of the remote. A non-zero `returncode` from this check — or from
       `_dirty_tree_attention`'s own `git status` call — fails CLOSED
       (`needs-attention`, step-8 code-review F-2), never silently
       read as "nothing to worry about"."""
    tmp_files = sorted(p.relative_to(tdir).as_posix() for p in tdir.rglob("*.tmp"))
    if tmp_files:
        return f"stray {tmp_files[0]} left by an interrupted write"
    note = tdir / AUDIT_NOTE
    if note.is_file():
        try:
            runs = json.loads(note.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runs = None
        if (isinstance(runs, list) and runs and isinstance(runs[-1], dict)
                and runs[-1].get("status") == "pending"):
            if runs[-1].get("restore_failed"):
                return (
                    f"{AUDIT_NOTE} has an unfinished ('pending') run entry "
                    "whose own restore attempt ALSO failed to put every file "
                    "back (step-9, external review F-1) — at least one file "
                    "may still be sitting in the NEW shape. Recover by "
                    "comparing each listed file's sha256 against its "
                    "sha256_before/sha256_after: restore any mismatched file "
                    "from the tar backup, or — if every file already matches "
                    "sha256_after — mark the entry \"complete\" by hand, then "
                    "re-run the migration."
                )
            return (
                f"{AUDIT_NOTE} has an unfinished ('pending') run entry — a "
                "prior migration was interrupted. Recover by comparing each "
                "listed file's sha256 against its sha256_before/sha256_after: "
                "restore any mismatched file from the tar backup, or — if "
                "every file already matches sha256_after — mark the entry "
                '"complete" by hand, then re-run the migration.'
            )
    if feature_on:
        rev = state_sync._git(
            ["rev-list", "--count", "@{upstream}..HEAD", "--", f"tickets/{tdir.name}/"],
            kdir)
        if rev.returncode != 0:
            return "could not check klc-state status (git rev-list failed)"
        ahead = int(rev.stdout.strip() or "0")
        if ahead > 0:
            return (
                f"{ahead} local klc-state commit(s) touching this ticket "
                "are not yet pushed to its upstream (a prior run's commit "
                "succeeded but its push was interrupted) — push klc-state, "
                "then re-run the migration"
            )
    return None


def _dirty_tree_attention(tdir: Path, kdir: Path, plan_nonempty: bool) -> str | None:
    """Step-8 (external review F-2): the feature-ON "any uncommitted
    change" signal that step-7 ran unconditionally — flagging ordinary,
    unrelated in-progress work on a ticket with NOTHING to migrate just as
    readily as a genuinely half-migrated one. Run once `plan_ticket` has
    decided whether the ticket has planned changes (or failed to plan at
    all — also treated as "not empty", conservatively): a ticket WITH
    planned changes still escalates on ANY dirt under its subtree (keeps
    F-9's guarantee that nothing but the migration's own planned files is
    ever part of its commit); a ticket whose plan is EMPTY escalates only
    when the dirty paths include the audit note or one of the migratable
    findings/verdict files (`_dirt_touches_migratable`) — a sign that SOME
    earlier run touched this ticket without finishing, not just an
    operator session's unrelated edit. A non-zero `git status` returncode
    fails CLOSED, same as the rev-list check above."""
    status = state_sync._git(
        ["status", "--porcelain", "--", f"tickets/{tdir.name}/"], kdir)
    if status.returncode != 0:
        return "could not check klc-state status (git status failed)"
    dirty = status.stdout.strip()
    if not dirty:
        return None
    if plan_nonempty or _dirt_touches_migratable(dirty, tdir.name):
        return "uncommitted changes under this ticket in the klc-state worktree"
    return None


def _sync_state_or_refuse(kdir: Path) -> None:
    """Step-7 (external review F-2); step-8 narrows this to the REAL run
    only (see `_check_dry_run_not_stale` for the dry run's own, non-
    mutating check). The real run must see the shared `klc-state` as the
    remote holds it, not a stale local copy, BEFORE the pre-plan decides
    anything — a straggler another peer pushed must be visible.
    `pull_rebase_preserving` already tolerates ordinary per-ticket dirt (it
    stashes and restores tracked changes around the rebase); any FAILURE
    of that pull (a genuine stash-pop conflict, a rebase conflict, no
    reachable remote, …) is surfaced loudly here as `MigrationRefused`
    (exit 2) rather than a raw traceback or — worse — a silently stale
    read.

    Decided: a per-ticket leftover from an earlier interrupted run is
    deliberately NOT refused here. It is surfaced per-ticket as
    `needs-attention` by `migrate`'s main loop (F-1/F-9) so the rest of
    the batch still makes progress — exactly what the HIGH finding asked
    for ('reports it, never unchanged', not 'refuses the whole run')."""
    try:
        state_sync.pull_rebase_preserving(kdir)
    except Exception as exc:
        raise MigrationRefused(
            f"could not sync klc-state before migrating: {exc}") from exc


def _check_dry_run_not_stale(kdir: Path) -> None:
    """Step-8 (external review F-3): AC-1 says a dry run 'writes nothing
    and takes no lock' — the step-7 `_sync_state_or_refuse` pulled (and on
    a stash-pop conflict could `git reset --hard`) the klc-state worktree
    even in DRY-RUN mode, which contradicts that guarantee and could race
    a live verb's own `state_tx`. A dry run now only FETCHES the upstream
    (no merge, no stash, no working-tree mutation of any kind) and refuses
    loudly (`MigrationRefused`, exit 2) when the local branch is behind
    it — a straggler the dry run cannot safely read without pulling is
    instead reported as a reason to run the migration for real (or pull by
    hand) first. A failure of the fetch itself refuses the same way."""
    fetch = state_sync._git(["fetch"], kdir)
    if fetch.returncode != 0:
        raise MigrationRefused(
            "could not fetch klc-state's upstream before a dry run: "
            f"{fetch.stderr.strip() or fetch.stdout.strip()}")
    behind = state_sync._git(["rev-list", "--count", "HEAD..@{upstream}"], kdir)
    if behind.returncode != 0:
        raise MigrationRefused(
            "could not check klc-state status before a dry run: "
            f"{behind.stderr.strip() or behind.stdout.strip()}")
    count = int(behind.stdout.strip() or "0")
    if count > 0:
        raise MigrationRefused(
            f"local klc-state is {count} commit(s) behind its upstream; "
            "run the migration for real (or pull klc-state by hand) "
            "before trusting a dry run")


def migrate(tickets_root, *, dry_run: bool = False, order_seed: int | None = None) -> dict:
    """Visit every ticket directory that has a `meta.json` under
    *tickets_root*, after `_check_preconditions` (AC-11) refuses an
    unsuitable root or an outdated `spec_review` before the first ticket is
    visited. A read-only pre-plan decides whether a ticket has any change
    at all — an unchanged ticket takes no lock, enters no transaction and
    gets no audit entry. With `dry_run=True` a ticket with changes is
    listed `would-rewrite` and nothing more is done (no lock, no
    transaction, no write — AC-1); otherwise it is written through
    `_migrate_one` (one `acquire_lock` + one `state_tx`, re-planned on the
    pulled state). Any exception while pre-planning a ticket — including
    one that `plan_ticket` itself does not catch (an unexpected exception
    from the mapping) — becomes one `failed` row in EITHER mode, so one
    malformed ticket never stops the batch (AC-6). `order_seed`, when
    given, shuffles the visiting order deterministically (AC-12's property
    test) — the engine makes no promise that migrating in a different
    order changes the OUTCOME, only that nothing here depends on
    alphabetical order.

    Step-7: when the multi-user feature is ON, the real run's
    `_sync_state_or_refuse` pulls `klc-state` once up front before any
    ticket is visited; step-8 gives the dry run its OWN, non-mutating
    up-front check instead (`_check_dry_run_not_stale`: fetch and refuse
    if behind, never pull/stash/reset). Per ticket, `_needs_attention` runs
    BEFORE `plan_ticket`; a flagged ticket is listed `needs-attention` and
    left completely alone (no plan, no lock, no write). Once `plan_ticket`
    has run, `_dirty_tree_attention` (feature ON, step-8) makes the SAME
    `needs-attention` call plan-aware: any dirt escalates a ticket with
    planned changes, but only audit-note/migratable-file dirt escalates a
    ticket whose plan is empty."""
    tickets_root = Path(tickets_root)
    _check_preconditions(tickets_root)
    feature_on = state_feature.enabled()
    kdir = klc_dir()
    if feature_on:
        if dry_run:
            _check_dry_run_not_stale(kdir)
        else:
            _sync_state_or_refuse(kdir)
    keys = sorted(p.name for p in tickets_root.iterdir()
                 if p.is_dir() and (p / "meta.json").is_file())
    if order_seed is not None:
        import random
        random.Random(order_seed).shuffle(keys)
    rows = []
    for key in keys:
        tdir = tickets_root / key
        attention = _needs_attention(tdir, kdir, feature_on)
        if attention:
            rows.append(_row(key, "needs-attention", reason=attention))
            continue
        plan = None
        plan_exc = None
        try:
            plan = plan_ticket(tdir)
        except Exception as exc:  # noqa: BLE001 - the per-ticket catch-all (impl-plan-review F-2)
            plan_exc = exc
        if feature_on:
            plan_nonempty = plan_exc is not None or bool(plan.changes) or bool(plan.reason)
            attention = _dirty_tree_attention(tdir, kdir, plan_nonempty)
            if attention:
                rows.append(_row(key, "needs-attention", reason=attention))
                continue
        if plan_exc is not None:
            rows.append(_row(key, "failed", reason=f"{type(plan_exc).__name__}: {plan_exc}"))
            continue
        if plan.reason:
            rows.append(_row(key, "failed", reason=plan.reason))
            continue
        if not plan.changes:
            rows.append(_row(key, "unchanged"))
            continue
        if dry_run:
            rows.append(_row(key, "would-rewrite", changes=plan.changes))
            continue
        rows.append(_migrate_one(tdir))
    return _report(rows, dry_run=dry_run)


def render_report(report: dict) -> str:
    """The Q-005 human-readable line layout: one line per changed/failed/
    skipped/needs-attention file or ticket, and a summary line with the
    totals. Step-7 (F-3): a dry run's summary prints the would-change
    totals instead of the (always zero) rewritten-files count."""
    lines = []
    for row in report["tickets"]:
        ticket = row["ticket"]
        status = row["status"]
        if status in ("rewritten", "would-rewrite"):
            verb = "would rewrite" if status == "would-rewrite" else "rewrote"
            for f in row["files"]:
                lines.append(f"{ticket}  {f['path']}  {f['old_count']} -> "
                            f"{f['new_count']} findings  {verb}")
        elif status == "unchanged":
            lines.append(f"{ticket}  unchanged")
        elif status == "failed":
            lines.append(f"{ticket}  failed: {row['reason']}")
        elif status == "skipped":
            lines.append(f"{ticket}  skipped: {row['reason']}")
        elif status == "needs-attention":
            lines.append(f"{ticket}  needs attention: {row['reason']}")
    if "would_change_files" in report:
        lines.append(f"summary: {len(report['tickets'])} ticket(s), "
                    f"{report['would_change_files']} file(s) in "
                    f"{report['would_change_tickets']} ticket(s) would change, "
                    f"{report['failed']} failed, {report['skipped']} skipped, "
                    f"{report['needs_attention']} needs attention")
    else:
        lines.append(f"summary: {len(report['tickets'])} ticket(s), "
                    f"{report['files_changed']} file(s) changed, "
                    f"{report['failed']} failed, {report['skipped']} skipped, "
                    f"{report['needs_attention']} needs attention")
    return "\n".join(lines)


def cli(tickets_root, *, dry_run: bool = False, as_json: bool = False) -> int:
    """`handback.py migrate`'s whole behaviour (AC-1/AC-11/AC-17). Step-7:
    a `needs-attention` ticket also makes the exit code non-zero — the
    re-run AC-5 expects to confirm zero must never pass silently over one."""
    try:
        report = migrate(tickets_root, dry_run=dry_run)
    except MigrationRefused as exc:
        print(f"handback migrate: refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False) if as_json else render_report(report))
    return 1 if report["failed"] or report["skipped"] or report["needs_attention"] else 0
