#!/usr/bin/env python3
"""provenance.py — KLC-116: `evidence=observed|read|assumed` on claims.

Every FACT/ASSUMPTION/DECISION item may DECLARE how its claim was
established. A declared label brings its companion: a probe transcript for
`observed`, a resolving `<file>:<line>` for `read`, a non-empty `if-false`
consequence for `assumed`. Absence never fails here (C-001) — only a
DECLARED-but-uncompanioned label does.

This module owns every rule that needs the filesystem. `items.py` (the
shared parser every consumer imports) is left alone (ADR-116 decision 1);
`items.iter_items` keeps walking `_superseded/` snapshots exactly as it does
today, and THIS module scopes its own reads away from them (D-202) — a
frozen snapshot is history, not an artefact anyone is deciding against. The
scoping also drops a stale legacy `_prompt*.md` card (KLC-118 moved cards to
`.klc/scratch/`; a card still physically sitting in the ticket tree is a
leftover, never a provenance item — Q-105 ruling).

Degrade-not-fail (C-004) is the caller's job at each call site: nothing in
THIS module needs to raise for that discipline to hold, but every public
entry point here is written so a caller can wrap it in one try/except and
degrade to a single surfaced note.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root_dir = _file_dir.parent.parent
for _p in (str(_project_root_dir), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.shared.paths import design_doc_path, klc_ticket_dir, klc_ticket_meta_file, project_root  # noqa: E402
import items as _items  # noqa: E402

EVIDENCE_VALUES = _items.EVIDENCE_VALUES

# A required <file>:<line> group (D-006) — a bare path is a SHAPE failure,
# not a claim that "still resolves" (impl-plan-review F-1 / design D-201).
_SRC_RE = re.compile(r"^([^\s:]+):(\d+)$")
_FENCE_RE = re.compile(r"^\s*```")
_HEADER_RE = _items.HEADER_RE

_SNAPSHOT_SEGMENT = "_superseded"
# Q-105 ruling: a stale legacy prompt card (pre-KLC-118 cards lived inside the
# ticket tree) must never be read as a provenance item, exactly like a frozen
# `_superseded/` snapshot.
_LEGACY_CARD_RE = re.compile(r"^_prompt.*\.md$")


@dataclass
class Finding:
    dimension: str      # companion | load-bearing | counts | override | degraded
    severity: str       # block | surface
    message: str
    item_id: str = ""
    file: str = ""
    line: int = 0
    channel: str = ""   # document | step-premise, filled by the load-bearing rules


# --- archival scoping (D-202, Q-105) -----------------------------------------

def _is_snapshot(parts) -> bool:
    """True when a ticket-relative path is history, not a live artefact:
    inside a frozen `_superseded/<timestamp>/` snapshot, or a stale legacy
    `_prompt*.md` card left behind in the ticket tree."""
    parts = tuple(parts)
    if _SNAPSHOT_SEGMENT in parts:
        return True
    return bool(parts) and bool(_LEGACY_CARD_RE.match(parts[-1]))


def _rel_parts(path, root: Path) -> tuple:
    try:
        return Path(path).resolve().relative_to(root.resolve()).parts
    except ValueError:
        return Path(path).parts


def _scoped_items(ticket: str) -> list:
    """Every LIVE item of the ticket — never a frozen `_superseded/` snapshot
    or a stale legacy card (D-202, Q-105). `items.iter_items` itself is left
    untouched; this is the filter every rule in this module reads through."""
    root = klc_ticket_dir(ticket)
    return [it for it in _items.iter_items(root)
            if not _is_snapshot(_rel_parts(it.file, root))]


def _scoped_index(ticket: str) -> dict:
    """The ticket item index (AC-1's contract) with snapshot/legacy-card
    records dropped. A live item's evidence is what every consumer reads."""
    idx = _items.build_index(ticket, write=False)["items"]
    return {i: r for i, r in idx.items() if not _is_snapshot(Path(r["file"]).parts)}


def _rel_file(item, root: Path) -> str:
    try:
        return str(Path(item.file).resolve().relative_to(root.resolve()))
    except ValueError:
        return item.file


# --- the three companion rules (AC-3, AC-4, AC-5) ----------------------------

def _read_lines(path: str) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _has_adjacent_probe(item) -> bool:
    """A fence inside the item's own quoted body, or the first fence after it
    with no other item header in between (spec's own "adjacent probe" def)."""
    if any(_FENCE_RE.match(b) for b in item.body):
        return True
    lines = _read_lines(item.file)
    start = item.line + len(item.body)  # 0-based index, first line after body
    for raw in lines[start:]:
        if _HEADER_RE.match(raw):
            return False
        if _FENCE_RE.match(raw):
            return True
    return False


def check_artefacts(ticket: str) -> list[Finding]:
    """The three companion rules, over live artefacts only (D-202). Absence
    of `evidence` is never checked here — that is `absence_warning`'s job."""
    root = klc_ticket_dir(ticket)
    out: list[Finding] = []
    for item in _scoped_items(ticket):
        ev = (item.attrs.get("evidence") or "").strip().lower()
        if not ev or ev not in EVIDENCE_VALUES:
            continue  # absence never fails here (C-001); an unknown value is items.py's job
        rel = _rel_file(item, root)
        if ev == "observed" and not _has_adjacent_probe(item):
            out.append(Finding(
                "companion", "block",
                f"{item.id} declares evidence=observed but has no adjacent probe "
                "transcript (a fenced command+output block)",
                item_id=item.id, file=rel, line=item.line))
        elif ev == "read":
            src = (item.attrs.get("src") or "").strip()
            m = _SRC_RE.match(src)
            if not m:
                out.append(Finding(
                    "companion", "block",
                    f"{item.id} declares evidence=read but src is absent or not in "
                    "<file>:<line> shape",
                    item_id=item.id, file=rel, line=item.line))
            elif not (project_root() / m.group(1)).exists():
                out.append(Finding(
                    "companion", "block",
                    f"{item.id} declares evidence=read but src names a path that "
                    f"does not exist in the repository: {m.group(1)}",
                    item_id=item.id, file=rel, line=item.line))
        elif ev == "assumed" and not (item.attrs.get("if-false") or "").strip():
            out.append(Finding(
                "companion", "block",
                f"{item.id} declares evidence=assumed but carries no non-empty "
                "if-false consequence",
                item_id=item.id, file=rel, line=item.line))
    return out


def absence_warning(ticket: str) -> str:
    """One warning line per artefact naming the artefact and the count of
    items with no `evidence` attribute at all (AC-6) — empty string when
    every scoped item declares one (or there are none)."""
    root = klc_ticket_dir(ticket)
    counts: dict[str, int] = {}
    for item in _scoped_items(ticket):
        if item.type not in ("FACT", "ASSUMPTION", "DECISION"):
            continue
        if (item.attrs.get("evidence") or "").strip():
            continue
        rel = _rel_file(item, root)
        counts[rel] = counts.get(rel, 0) + 1
    if not counts:
        return ""
    return "; ".join(
        f"provenance[absence]: {f}: {n} item(s) carry no evidence attribute"
        for f, n in sorted(counts.items())
    )


# --- the load-bearing set, derived from structure alone (AC-11) -------------

DOCUMENT = "document"
STEP_PREMISE = "step-premise"

# Any level-2 heading ends the PREVIOUS heading's section — not just another
# Option heading — so a trailing `## Decisions` section (the shape every real
# shipped design document uses) is never swallowed into the last option's span.
_ANY_H2_RE = re.compile(r"^##\s+")
_OPTION_HEADING_RE = re.compile(r"(?i)^##\s+Option\b.*$")
# design.md nests its options one level down (`### Option A`) under `## Options`.
_H3_OPTION_HEADING_RE = re.compile(r"(?i)^###\s+Option\b.*$")
_ANY_H2_H3_RE = re.compile(r"^#{2,3}\s+")
# Both spellings seen in shipped design documents (F-002): `(recommended)` and
# `(recommended: true)`.
_RECOMMENDED_RE = re.compile(r"(?i)\(\s*recommended(\s*:\s*true)?\s*\)")
_ITEM_ID_RE = re.compile(r"\b[A-Z]+-[\w-]+\b")


def _option_section_line_spans(text: str) -> list[tuple[int, int, bool]]:
    """[(start_line, end_line_exclusive, recommended)] per `## Option` heading,
    1-indexed to match `item.line`/index `line` numbering."""
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if _ANY_H2_H3_RE.match(ln)]
    spans = []
    for k, idx in enumerate(heads):
        h2 = _OPTION_HEADING_RE.match(lines[idx])
        if not (h2 or _H3_OPTION_HEADING_RE.match(lines[idx])):
            continue
        # a `## Option` span ends at the next `##`; a `### Option` one at the next `##`/`###`
        nxt = [h for h in heads[k + 1:] if not h2 or _ANY_H2_RE.match(lines[h])]
        end = nxt[0] if nxt else len(lines)
        spans.append((idx + 1, end + 1, bool(_RECOMMENDED_RE.search(lines[idx]))))
    return spans


def load_bearing(ticket: str) -> tuple[dict, list]:
    """The id→channel mapping (D-205: an id is `document` or `step-premise`,
    never a flat set) plus the degraded notes from deriving it. No model call,
    no semantics — pure structure (C-005)."""
    index = _scoped_index(ticket)
    notes: list[Finding] = []
    channels: dict[str, str] = {}

    options_path = design_doc_path(ticket)
    options_rel = options_path.relative_to(klc_ticket_dir(ticket)).as_posix()
    options_text = options_path.read_text(encoding="utf-8") if options_path.exists() else ""
    spans = _option_section_line_spans(options_text)
    if spans and not any(r for _, _, r in spans):
        notes.append(Finding(
            "degraded", "surface",
            "no option heading carries a recommended marker — option sections "
            "excluded from the load-bearing set"))
    excluded = [(s, e) for s, e, r in spans if not r]

    # Document-level channel: any evidence-bearing item type (D-005 explicitly
    # discusses a document-channel ASSUMPTION, not only DECISION) sitting in
    # `design.md` (or legacy `design/options.md`) outside every excluded (non-recommended) span.
    for item_id, rec in index.items():
        if (rec["type"] in ("DECISION", "ASSUMPTION", "FACT")
                and rec["status"] == "active"
                and rec["file"] == options_rel
                and not any(s <= rec["line"] < e for s, e in excluded)):
            channels[item_id] = DOCUMENT

    impl_plan_path = klc_ticket_dir(ticket) / "impl-plan.md"
    if impl_plan_path.exists():
        import impl_plan_check as _ipc
        text = impl_plan_path.read_text(encoding="utf-8")
        for step in _ipc.parse_impl_plan_steps(text):
            depends = _ipc.extract_step_fields(step["body"])["depends_on"]
            for token in _ITEM_ID_RE.findall(depends):
                if token in index:
                    channels[token] = STEP_PREMISE  # stricter channel wins (D-206)
                else:
                    notes.append(Finding(
                        "degraded", "surface",
                        f"{step['id']} names premise {token}, which is not an "
                        "item in this ticket"))
    return channels, notes


# --- the design-acceptance gate (AC-7, AC-8, AC-9, AC-10) --------------------

def _deferred_provenance(ticket: str) -> list[str]:
    """`meta.json:deferred_provenance` — the operator override naming exact
    excused item ids (Q-002's resolution: names ids, never a global switch)."""
    try:
        meta = json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return []
    return list(meta.get("deferred_provenance") or [])


def design_gate(ticket: str, track: str) -> tuple[str, list[str]]:
    """`(block_message, warn_lines)` in the shape `_spec_quality_gate` already
    uses. `block_message` is non-empty only on M/L with at least one
    unexcused, unmeasured load-bearing decision (AC-7). XS computes nothing
    (AC-9); S computes the identical list but never blocks (AC-8) — the
    caller decides that by never reaching this function with track M/L logic
    applied, but the check is repeated here too so a caller cannot mis-wire
    it into a block on S.
    """
    track = (track or "").strip().upper()
    if track == "XS":
        return "", []  # AC-9: computes nothing

    channels, load_notes = load_bearing(ticket)
    index = _scoped_index(ticket)
    excused = set(_deferred_provenance(ticket))

    warns: list[str] = [f"provenance[degraded]: {n.message}" for n in load_notes]
    offenders: list[str] = []
    excused_hit: list[str] = []

    for item_id in sorted(channels):
        rec = index.get(item_id)
        if rec is None:
            continue
        channel = channels[item_id]
        ev = rec.get("evidence")

        # D-206: an ASSUMPTION reached ONLY through the document channel
        # already declares itself a guess — surfaced, never blocking. The
        # step-premise channel drops the exemption: a build step literally
        # depends on it, which is exactly the expensive-wrong-premise case.
        if rec["type"] == "ASSUMPTION" and channel == DOCUMENT:
            warns.append(f"provenance[exempt]: [{channel}] {item_id} "
                        f"({rec['file']}:{rec['line']}) is an ASSUMPTION in the "
                        "document channel — surfaced, not blocking")
            continue

        if ev in (None, "assumed"):
            label = ev or "no evidence attribute"
            line = f"[{channel}] {item_id} ({rec['file']}:{rec['line']}) {label}"
            if item_id in excused:
                excused_hit.append(item_id)
                warns.append(f"provenance[override]: {line} — excused by "
                            "meta.deferred_provenance")
            else:
                offenders.append(line)

    if excused_hit:
        warns.append(
            f"provenance[override:count]: {len(excused_hit)} of "
            f"{len(excused_hit) + len(offenders)} load-bearing offender(s) "
            "excused by meta.deferred_provenance")
    for unknown in sorted(excused - set(channels)):
        warns.append(f"provenance[override:unknown]: {unknown} named in "
                    "meta.deferred_provenance is not a load-bearing item in "
                    "this ticket")

    warns += counts_advisory_lines(ticket)

    if offenders and track in ("M", "L"):
        msg = ("provenance: " + str(len(offenders)) + " load-bearing decision(s) "
               "without measurement — " + "; ".join(offenders) +
               "; set meta.deferred_provenance to ack past named ids")
        return msg, warns

    warns += [f"provenance[load-bearing]: {o}" for o in offenders]
    return "", warns


# --- per-artefact counts (AC-14) ---------------------------------------------

def counts_in_text(text: str) -> dict:
    """Pure, filesystem-free: the observed/read/assumed tally over item
    headers found directly in *text* (used by `spec_selfcheck` on `spec.md`,
    which never reads a ticket directory itself)."""
    out = {"observed": 0, "read": 0, "assumed": 0}
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if not m:
            continue
        ev = (_items._parse_attrs(m.group("attrs")).get("evidence") or "").lower()
        if ev in out:
            out[ev] += 1
    return out


def _counts_per_file(ticket: str) -> dict:
    """observed/read/assumed tallies per LIVE artefact (D-202: a frozen
    `_superseded/` snapshot never contributes)."""
    root = klc_ticket_dir(ticket)
    per_file: dict[str, dict] = {}
    for item in _scoped_items(ticket):
        ev = (item.attrs.get("evidence") or "").strip().lower()
        if ev not in EVIDENCE_VALUES:
            continue
        rel = _rel_file(item, root)
        per_file.setdefault(rel, {"observed": 0, "read": 0, "assumed": 0})[ev] += 1
    return per_file


def counts_advisory_lines(ticket: str) -> list[str]:
    """One warn-only line per artefact that holds at least one attributed
    item (AC-14) — an artefact with none contributes no line at all."""
    return [
        f"provenance[counts]: {f}: observed={c['observed']} read={c['read']} "
        f"assumed={c['assumed']}"
        for f, c in sorted(_counts_per_file(ticket).items())
    ]


# --- the retrospective's contradicted-assumption count (AC-15) --------------

def report(ticket: str) -> dict:
    """Per-artefact counts plus `contradicted_assumed`: the number of
    `evidence=assumed` items a LATER item superseded or explicitly refuted —
    the union of two edges the scoped index already carries, no new parser
    needed (D-008: `refutes=` is already an arbitrary attribute)."""
    recs = _scoped_index(ticket)
    refuted = {r for rec in recs.values()
               for r in (rec["attrs"].get("refutes") or "").replace(",", " ").split()}
    contradicted = sorted(
        i for i, rec in recs.items()
        if rec.get("evidence") == "assumed" and (rec.get("superseded_by") or i in refuted)
    )
    return {
        "ticket": ticket,
        "per_artefact": _counts_per_file(ticket),
        "contradicted_assumed": len(contradicted),
        "contradicted_ids": contradicted,
    }


# --- CLI ----------------------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    findings = check_artefacts(args.ticket)
    for f in findings:
        print(f"{f.dimension}: {f.message} ({f.file}:{f.line})")
    warn = absence_warning(args.ticket)
    if warn:
        print(warn)
    return 1 if findings else 0


def cmd_report(args: argparse.Namespace) -> int:
    print(json.dumps(report(args.ticket), indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="the three companion rules over live artefacts")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="per-artefact counts + contradicted-assumed")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
