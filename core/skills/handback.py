#!/usr/bin/env python3
"""handback.py — the one intake seam every reviewer hand-back passes through
(KLC-127).

Five finding shapes used to live on disk and no code validated what a
reviewer handed back (F-002, F-005, F-008 in the ticket's discovery). This
module is the six-kind registry (`KINDS`) plus the two validators:

  `validate_handback(kind, doc)`  — a reviewer's own verdict object, fresh off
                                    the wire: `{"findings": [...],
                                    "decisions_to_confirm": [...]}`. Stricter
                                    than `validate_findings` — a finding's
                                    `reviewer` field, if present, must equal
                                    `kind` (or be empty), and the KLC-154
                                    migration's `LEGACY_RULE_NAME` is refused
                                    here (a hand-back is never the migration).
  `validate_findings(kind, items)` — an already-stored or pooled list of
                                    Finding dicts, where `reviewer` may be any
                                    reviewer slug (a headless reviewer name
                                    such as `architecture`) and
                                    `LEGACY_RULE_NAME` is accepted (D-118).

The per-record rules (the one Finding shape itself) live in
`findings.check_findings`; this module only adds the two entry points, the
six-kind registry, and — from step-3 on — `take`, the CLI that stores a valid
hand-back and counts its review pass.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings  # noqa: E402
import review_plan  # noqa: E402
import spec_review  # noqa: E402
from _paths import framework_root, klc_ticket_dir, project_root  # noqa: E402


@dataclass(frozen=True)
class KindSpec:
    """One review kind's registry entry.

    `rule_names` is `None` for the two in-client kinds (code-review,
    external-review): their vocabulary is free-form slugs, not a fixed list.
    `topics` is the kind's allowed `decisions_to_confirm` topics — an empty
    tuple for code-review/external-review, which carry no decisions at all
    (AC-3: `decisions_to_confirm` must be empty for those two).
    """
    name: str
    rule_names: Optional[tuple]
    topics: tuple
    artefact: str
    stored: Optional[str]
    plan_reviewer: Optional[str]
    counts_in_rate: bool
    binding: object = None          # the ReviewKind of an independent kind, else None


def _kinds() -> dict:
    import testplan_review
    import implplan_review
    import drift_review

    def ind(rk, artefact, plan_reviewer=None, counts=False):
        return KindSpec(rk.name, rk.finding_categories, rk.decision_topics, artefact,
                        None, plan_reviewer, counts, rk)

    return {
        "spec": ind(spec_review.SPEC_REVIEW, "spec.md"),
        "test-plan": ind(testplan_review.TEST_PLAN_REVIEW, "test-plan.md"),
        "impl-plan": ind(implplan_review.IMPL_PLAN_REVIEW, "impl-plan.md"),
        "drift": ind(drift_review.DRIFT_CHECK, "spec.md", "drift", counts=True),
        "code-review": KindSpec("code-review", None, (), "", "review/code-review-findings.json",
                                "code-review", True),
        "external-review": KindSpec("external-review", None, (), "",
                                    "review/external-review-findings.json", "external", True),
    }


KINDS = _kinds()

# step-13/item-3: the same intake-key shape `core/phases/intake.py`'s
# DEFAULT_KEY_RE enforces at creation (duplicated, not imported, to keep
# handback.py's own dependency surface — core/skills only, no core/phases
# edge). Anchored on both ends, so it also rules out a path separator or
# `..` anywhere in the value: `--ticket` is joined straight onto
# `klc_ticket_dir()` with no further sanitising, and a non-matching value
# must never reach that join.
_TICKET_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def validate_findings(kind, items) -> list[str]:
    """Validate a STORED or POOLED list of Finding dicts for *kind*.

    Used for a findings file already on disk (or a headless reviewer's
    partial): `reviewer` may be any slug, and `LEGACY_RULE_NAME` is accepted
    (it is written only by the KLC-154 migration, D-118).
    """
    spec = KINDS.get(kind)
    if spec is None:
        return [f"unknown kind {kind!r} (one of {', '.join(KINDS)})"]
    if not isinstance(items, list):
        return ["findings must be a list"]
    return findings.check_findings(items, rule_names=spec.rule_names, kind=kind)


def _handback_findings(kind, items) -> list[str]:
    if items is None:
        items = []          # F-5 (step-12): a decisions-only verdict carries no
                            # `findings` key at all — parse_review's own rule
                            # (`doc.get("findings") or []`) treats that as empty,
                            # not an error; intake now agrees with the ack parser.
    if not isinstance(items, list):
        return ["findings must be a list"]
    return findings.check_findings(items, rule_names=KINDS[kind].rule_names, kind=kind,
                                   handback=True)


def validate_handback(kind, doc) -> list[str]:
    """Validate a reviewer's raw hand-back OBJECT for *kind*.

    Returns a list of named schema errors; empty means the hand-back is in
    the one shape and ready for `take` to store. Never raises — a malformed
    hand-back is data, not an exception.
    """
    if kind not in KINDS:
        return [f"unknown kind {kind!r} (one of {', '.join(KINDS)})"]
    if not isinstance(doc, dict):
        return ["the hand-back must be a JSON object with findings and decisions_to_confirm"]
    errors = _handback_findings(kind, doc.get("findings", None))
    decisions = doc.get("decisions_to_confirm", [])
    if not isinstance(decisions, list):
        return errors + ["decisions_to_confirm must be a list"]
    spec = KINDS[kind]
    if not spec.topics:
        return errors + ([f"{kind} has no decision topics; decisions_to_confirm must be empty"]
                         if decisions else [])
    finding_ids = {f.get("id") for f in doc.get("findings") or [] if isinstance(f, dict)}
    errors += [f"duplicate id {d.get('id')!r}" for d in decisions
               if isinstance(d, dict) and d.get("id") in finding_ids]
    out = spec_review.ReviewOutput(decisions_to_confirm=spec_review.decisions_from_raw(decisions))
    return errors + spec_review.validate(out, spec.binding)


# --- take: the one intake command ------------------------------------------

def _refuse(errors: list[str], *, ticket: str = "", kind: str = "", text: str = None,
           skip_save: bool = False) -> int:
    for err in errors:
        print(f"handback: refused: {err}", file=sys.stderr)
    if ticket and kind and text is not None and not skip_save:
        kept = _save_rejected(ticket, kind, text)
        if kept is not None:
            print(f"handback: raw answer kept at {kept}", file=sys.stderr)
            print("handback: retry with: python3 core/skills/handback.py take "
                 f"--kind {kind} --ticket {ticket} --file {kept}", file=sys.stderr)
    return 1


def _save_rejected(ticket: str, kind: str, text: str) -> Optional[Path]:
    """Never lose a refused answer (step-12/F-2): save the raw text beside the
    ticket's review artefacts so a retry after a schema fix can resubmit the
    same content. Degrade-not-fail: returns None on any write error."""
    import datetime as _dt
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        path = klc_ticket_dir(ticket) / "review" / f"{kind}-rejected-{ts}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None


def _is_rejected_copy(ticket: str, file: Path) -> bool:
    """step-13/item-3: True iff *file* is already one of THIS ticket's own
    previously-kept `review/<kind>-rejected-<ts>.txt` copies — re-saving it
    on a repeat failure would stamp a fresh timestamp on the same content
    every retry, multiplying copies forever instead of keeping the one the
    operator is already working from. Degrade-not-fail: any path error
    reads as "not a rejected copy" (save proceeds as before)."""
    try:
        resolved = Path(file).resolve()
        review_dir = (klc_ticket_dir(ticket) / "review").resolve()
    except OSError:
        return False
    return (resolved.parent == review_dir
           and "-rejected-" in resolved.name and resolved.name.endswith(".txt"))


def _atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def extract_verdict(text: str):
    """The last fenced JSON object that parses AND carries a `findings` or
    `decisions_to_confirm` key — anything else (prose, invalid JSON, a
    valid-but-unrelated object such as a completion signal) is not a
    parseable verdict.

    F-5 (step-12): walks every fenced candidate from last to first and
    returns the first one that qualifies, rather than checking only the
    single last-parseable-dict-of-any-shape (`spec_review._extract_json`'s
    own contract). The completion-signal include is appended to every
    reviewer prompt and asks for a JSON block as the LAST output, so a
    reviewer whose saved answer is verdict-then-signal must still resolve
    to the verdict, not None."""
    candidates = list(spec_review._JSON_FENCE_RE.findall(text))
    if not candidates:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            candidates = [stripped]
    for raw in reversed(candidates):
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(doc, dict) and ("findings" in doc or "decisions_to_confirm" in doc):
            return doc
    return None


def take(kind: str, ticket: str, file: Path) -> int:
    """Validate, store and count one reviewer hand-back.

    Fail-closed (AC-5): any schema error, an unreadable file, or no
    parseable JSON verdict writes nothing to the kind's own path and returns
    1, printing every error. A schema error or an unparseable-but-readable
    verdict (step-12/F-2) also keeps the raw text at
    `review/<kind>-rejected-<ts>.txt` and prints the exact retry command — a
    one-shot provider's answer is never simply lost, UNLESS *file* is
    already one of this ticket's own kept rejected copies (step-13/item-3:
    a retry of a retry must not multiply copies). A valid verdict (AC-6)
    is stored as Finding dicts at the kind's own path (code-review/
    external-review only; the four independent kinds write no file here —
    their ack-time parser does that, step-5) and (AC-7/AC-8) counts exactly
    one reviewer-tagged pass for code-review, external-review and drift.

    step-13/item-3: *ticket* must match the intake key shape (`_TICKET_RE`)
    AND already have a `meta.json` — refused before anything is read or
    written, so a typo'd or hostile ticket string can never create
    `.klc/tickets/<typo>/review/` out of thin air.
    """
    if not _TICKET_RE.match(ticket or ""):
        return _refuse([f"invalid ticket key {ticket!r} (expected e.g. KLC-127)"])
    tdir = klc_ticket_dir(ticket)
    if not (tdir / "meta.json").is_file():
        return _refuse([f"unknown ticket {ticket!r}: no meta.json at {tdir}"])
    try:
        text = Path(file).read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return _refuse([f"verdict file unreadable: {exc}"])
    already_rejected = _is_rejected_copy(ticket, file)
    doc = extract_verdict(text)
    if doc is None:
        return _refuse(["no parseable JSON verdict (an object with findings) in the file"],
                       ticket=ticket, kind=kind, text=text, skip_save=already_rejected)
    errors = validate_handback(kind, doc)
    if errors:
        return _refuse(errors, ticket=ticket, kind=kind, text=text,   # keeps the raw answer
                       skip_save=already_rejected)                    # unless it is one already
    spec = KINDS[kind]
    if spec.stored:
        records = [findings.Finding.from_dict({**f, "reviewer": kind, "kind": kind}).to_dict()
                   for f in doc.get("findings") or []]
        try:
            _atomic_write_json(tdir / spec.stored, records)
        except OSError as exc:
            return _refuse([f"could not store {spec.stored}: {exc}"])
    if spec.plan_reviewer:
        _record(ticket, spec.plan_reviewer, Path(file))   # every refusal is one note
    print(f"handback: {kind} verdict for {ticket} accepted "
          f"({len(doc.get('findings') or [])} finding(s))")
    return 0


def _record(ticket, reviewer, output) -> None:
    if not (klc_ticket_dir(ticket) / "review-plan.json").is_file():
        try:
            planned = _run_planner(ticket)
        except (OSError, subprocess.SubprocessError) as exc:
            planned = False
            print(f"handback: note: planner failed ({exc})")
        if not planned and not (klc_ticket_dir(ticket) / "review-plan.json").is_file():
            print("handback: note: no review plan could be written; pass not recorded")
            return
    try:
        review_plan.record_pass(ticket, reviewer, output=output)
    except review_plan.RecordRefused as exc:
        print(f"handback: note: pass not recorded ({exc})")


def _run_planner(ticket) -> bool:
    spec_md = klc_ticket_dir(ticket) / "spec.md"
    diff_range = "main" + "." * 3 + "HEAD"
    rc = subprocess.run([sys.executable, str(framework_root() / "scripts" / "review.py"),
                        "--plan-only", "--diff", diff_range, "--spec", str(spec_md)],
                       cwd=str(project_root()), capture_output=True, text=True,
                       timeout=120).returncode
    return rc in (0, 2)                             # 2 = over the cap, plan already written


def _read_stored_findings(path: Path, kind: str, notes: list) -> list:
    """One stored/derived/headless findings file for *kind*: read, validate
    (stored mode — AC-17), stamp `reviewer`/`kind` from *kind* when a record
    lacks them (D-110), and return the `Finding` list. Any read/parse/schema
    failure appends one note and returns `[]` — never raises (fail-closed,
    skip-with-note)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        notes.append(f"{path.name}: unreadable ({exc})")
        return []
    if not isinstance(raw, list):
        notes.append(f"{path.name}: not a JSON list")
        return []
    errors = validate_findings(kind, raw)
    if errors:
        # F-7 (step-12): name the KLC-154 migration when the error IS the
        # old-shape marker, so the operator knows the fix, not just the symptom.
        old_shape = any("old independent shape" in e or "old in-client shape" in e
                       for e in errors)
        suffix = " (run the KLC-154 migration)" if old_shape else ""
        notes.append(f"{kind}: old shape or invalid in {path.name} "
                     f"({'; '.join(errors[:3])}){suffix}")
        return []
    out = []
    for d in raw:
        d = dict(d)
        if not d.get("reviewer"):
            d["reviewer"] = kind
        if not d.get("kind"):
            d["kind"] = kind
        out.append(findings.Finding.from_dict(d))
    return out


def load_ticket_findings(ticket_dir) -> tuple:
    """Every stored, derived and headless finding of one ticket directory
    (AC-17): the `code-review`/`external-review` stored files,
    `review/headless-findings.json` (D-111), and for each of the four
    independent kinds its derived `<kind>-review-findings.json` when it
    exists, else its `.md` verdict parsed read-only (never writing the
    derived JSON as a side effect, D-106). Returns `(items, notes)` —
    `notes` names every file skipped and why; nothing here ever raises."""
    ticket_dir = Path(ticket_dir)
    items: list = []
    notes: list = []

    for kind, spec in KINDS.items():
        if spec.stored:
            path = ticket_dir / spec.stored
            if path.is_file():
                items.extend(_read_stored_findings(path, kind, notes))
        else:
            derived = ticket_dir / f"{kind}-review-findings.json"
            if derived.is_file():
                items.extend(_read_stored_findings(derived, kind, notes))
            elif spec.binding is not None:
                md_path = ticket_dir / spec.binding.output_file
                if md_path.is_file():
                    try:
                        text = md_path.read_text(encoding="utf-8")
                    except OSError as exc:
                        notes.append(f"{md_path.name}: unreadable ({exc})")
                    else:
                        out = spec_review.parse_review(text, spec.binding)
                        items.extend(out.findings)

    headless = ticket_dir / "review" / "headless-findings.json"
    if headless.is_file():
        items.extend(_read_stored_findings(headless, "code-review", notes))

    return items, notes


def write_headless_findings(ticket: str, items: list) -> Optional[Path]:
    """D-111: write the validated, stamped headless findings for *ticket* to
    `review/headless-findings.json`, so `findings.py pool` counts the
    headless partials among the review kinds (`load_ticket_findings` reads
    this file as a `code-review` review kind). Degrade-not-fail: returns
    `None` on any write error or when *ticket* is not given, never raises."""
    if not ticket:
        return None
    try:
        path = klc_ticket_dir(ticket) / "review" / "headless-findings.json"
        _atomic_write_json(path, [f.to_dict() for f in items])
        return path
    except OSError:
        return None


def pool_main(argv) -> int:
    """`findings.py pool --ticket KEY` (AC-17): load every finding of the
    ticket, pool it (`findings.build_pool`), write
    `review/findings-pool.json`, and print the "N raw -> M pooled" line."""
    import argparse

    ap = argparse.ArgumentParser(prog="findings.py pool")
    ap.add_argument("--ticket", required=True)
    args = ap.parse_args(argv)

    tdir = klc_ticket_dir(args.ticket)
    items, notes = load_ticket_findings(tdir)
    for note in notes:
        print(f"findings pool: note: {note}", file=sys.stderr)

    pool = findings.build_pool(items, ticket=args.ticket,
                               min_similarity=findings.min_similarity())
    _atomic_write_json(tdir / "review" / "findings-pool.json", pool)
    print(f"findings pool: {pool['raw_count']} raw -> {pool['pooled_count']} pooled")
    return 0


def main(argv=None) -> int:
    import argparse

    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="handback", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_take = sub.add_parser("take", help="validate, store and count one reviewer hand-back")
    p_take.add_argument("--kind", required=True, choices=sorted(KINDS))
    p_take.add_argument("--ticket", required=True)
    p_take.add_argument("--file", required=True, type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "take":
        return take(args.kind, args.ticket, args.file)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
