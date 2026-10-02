#!/usr/bin/env python3
"""findings.py — structured finding schema and aggregation helpers for review pipeline.

Phase 1.2 of the review overhaul plan. Provides:
- Finding dataclass (JSON-serializable)
- aggregate(partials_dir) → list[Finding]
- similarity(a, b) → float, group(items, min_similarity) → list[list[Finding]] (KLC-127)
- dedupe(findings, min_similarity=None) → list[Finding]
- sort_for_report(findings) → list[Finding]

Used by scripts/review.py (aggregator) and core/agents/review/*.md output spec.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# KLC-127: the one Finding shape, shared by every reviewer and every hand-back.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_OLD_INDEPENDENT_KEYS = ("category", "detail", "suggested_fix")
LEGACY_RULE_NAME = "legacy-unclassified"      # written only by the KLC-154 migration (D-118)


@dataclass
class Finding:
    """Structured code review finding.

    Fields match the KLC-127 one-shape schema. `issue_id` is computed from
    (rule_name, file, line) to enable stable cross-run deduplication — unless
    `id`, `kind` or `ref` is non-empty, in which case those plus `title` are
    folded in too (AC-2), so a hand-stamped identity never collides with a
    positionally-identical finding from another reviewer.
    """
    rule_name: str
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    file: str
    line: Optional[int]
    title: str
    body: str
    fix: Optional[str]
    reviewer: str
    id: str = ""
    kind: str = ""
    ref: str = ""
    ac: str = ""
    issue_id: str = field(init=False, default="")

    def __post_init__(self):
        """Compute deterministic issue_id. Override after construction if needed."""
        payload = f"{self.rule_name}|{self.file}|{self.line}"
        if self.id or self.kind or self.ref:          # AC-2: unchanged when all empty
            payload += f"|{self.kind}|{self.id}|{self.ref}|{self.title}"
        self.issue_id = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def from_dict(cls, d: dict) -> Finding:
        """Deserialize from JSON dict."""
        # issue_id may or may not be in the dict; __post_init__ recomputes if missing
        raw_line = d.get("line")
        return cls(
            rule_name=d["rule_name"],
            severity=d["severity"],
            file=d["file"],
            line=None if raw_line is None else int(raw_line),
            title=d["title"],
            body=d["body"],
            fix=d.get("fix"),
            reviewer=d["reviewer"],
            id=str(d.get("id") or ""),
            kind=str(d.get("kind") or ""),
            ref=str(d.get("ref") or ""),
            ac=str(d.get("ac") or ""),
        )

    def to_dict(self) -> dict:
        """Serialize to JSON dict."""
        return asdict(self)


def check_findings(items, *, rule_names, kind, handback=False) -> list[str]:
    """Return a list of named schema errors for a list of raw finding dicts.

    Shared by `handback.validate_handback` (handback=True: the reviewer's own
    hand-back — `reviewer` must equal `kind` or be empty, and the KLC-154
    migration's `LEGACY_RULE_NAME` is refused) and `handback.validate_findings`
    (handback=False: a stored/pooled list — `reviewer` may be any reviewer slug,
    e.g. a headless reviewer name, and `LEGACY_RULE_NAME` is accepted). Empty
    return means every record is in the one Finding shape.
    """
    errors: list[str] = []
    seen: set = set()
    for n, rec in enumerate(items, start=1):
        if not isinstance(rec, dict):
            errors.append(f"finding #{n}: not an object")
            continue
        fid = rec.get("id") or f"#{n}"
        old = [k for k in _OLD_INDEPENDENT_KEYS if k in rec]
        if old:
            errors.append(f"finding {fid}: old independent shape ({', '.join(old)})")
            continue
        if not rec.get("id") or "rule_name" not in rec:
            errors.append(f"finding {fid}: old in-client shape (needs id and rule_name)")
            continue
        if fid in seen:
            errors.append(f"duplicate id {fid!r}")
        seen.add(fid)
        rn = rec.get("rule_name")
        known = isinstance(rn, str) and (rn in rule_names if rule_names else bool(_SLUG_RE.match(rn)))
        if rn == LEGACY_RULE_NAME:
            known = not handback                      # D-118: stored files only
        if not known:
            if rn == LEGACY_RULE_NAME:
                # KLC-154: this value is written only by the stored-files
                # migration (D-118) — a hand-back naming it is refused with
                # ITS OWN reason, never the generic "unknown"/kebab-case
                # wording (neither of which applies: the slug IS well-formed
                # and, for a fixed-vocabulary kind, not simply "unknown").
                errors.append(
                    f"finding {fid}: rule_name {rn!r} is reserved for the KLC-154 "
                    "migration of stored files and cannot be handed back; use a "
                    "rule_name from this kind's vocabulary")
            elif rule_names:
                errors.append(f"finding {fid}: unknown rule_name {rn!r}")
            else:
                # free-vocabulary kinds (code-review/external-review, step-12/F-2):
                # name the fix so a one-shot provider's reply can be corrected and
                # resubmitted, not just told "unknown".
                errors.append(
                    f"finding {fid}: unknown rule_name {rn!r} — rule_name must be a "
                    "lower-case kebab-case slug (letters, digits and hyphens only, "
                    "e.g. 'missing-test'), not snake_case, Title Case or a placeholder")
        if rec.get("severity") not in SEVERITIES:
            errors.append(f"finding {fid}: unknown severity {rec.get('severity')!r}")
        for key in ("file", "title", "body"):
            val = rec.get(key)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"finding {fid}: empty {key}")
        if isinstance(rec.get("title"), str) and "\n" in rec["title"]:
            errors.append(f"finding {fid}: title must be one line")
        line = rec.get("line")
        if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
            errors.append(f"finding {fid}: line must be a positive integer or null, got {line!r}")
        if rec.get("fix") is not None and not isinstance(rec.get("fix"), str):
            errors.append(f"finding {fid}: fix must be a string or null")
        if rec.get("kind") not in (None, "", kind):
            errors.append(f"finding {fid}: kind {rec.get('kind')!r} does not match {kind!r}")
        reviewer = rec.get("reviewer")
        if handback and reviewer not in (None, "", kind):       # AC-4: hand-backs only
            errors.append(f"finding {fid}: reviewer {reviewer!r} does not match kind {kind!r}")
        elif not handback and reviewer not in (None, "") and not _SLUG_RE.match(str(reviewer)):
            errors.append(f"finding {fid}: reviewer {reviewer!r} is not a slug")
    return errors


def _warn(notes: Optional[list], msg: str) -> None:
    if notes is not None:
        notes.append(msg)
    else:
        print(f"WARN: {msg}", file=sys.stderr)


def aggregate(partials_dir: Path, *, validate=None, notes: Optional[list] = None,
             kind: str = "") -> list[Finding]:
    """Load all findings.json from partials_dir/**/findings.json.

    Each reviewer's partial directory contains findings.json. The sentinel
    pass (Phase 3a) also writes partials_dir/sentinels/findings.json.

    Returns deduplicated, unsorted list. Caller should sort via
    sort_for_report() before rendering.

    KLC-127 AC-14: when *validate* is given (a callable taking the raw list
    and returning a list of schema errors, e.g.
    `lambda items: handback.validate_findings("code-review", items)`), the
    WHOLE file is left out — with one note, never partially accepted — if
    it fails; a file that passes has every entry stamped `reviewer` (the
    partial's own directory name) and `kind` (*kind*) before construction.
    Without *validate* (the original, still-supported call shape), no
    stamping happens and nothing is rejected at the file level — only a
    malformed individual entry is skipped, matching today's behaviour.

    Warnings are appended to *notes* when given, else printed to stderr
    (unchanged default behaviour); malformed entries are skipped, not fatal.
    """
    out: list[Finding] = []

    if not Path(partials_dir).exists():
        return out

    for findings_file in sorted(Path(partials_dir).rglob("findings.json")):
        try:
            with findings_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _warn(notes, f"cannot read {findings_file}: {e}")
            continue

        if not isinstance(data, list):
            _warn(notes, f"{findings_file} is not a JSON list; skipping")
            continue

        reviewer = findings_file.parent.name
        if validate is not None:
            errors = validate(data)
            if errors:
                _warn(notes, f"partial {reviewer} left out: {'; '.join(errors[:3])}")
                continue
            data = [{**d, "reviewer": reviewer, "kind": kind} for d in data]

        for item in data:
            try:
                out.append(Finding.from_dict(item))
            except (KeyError, TypeError, ValueError) as e:
                _warn(notes, f"{findings_file} has malformed entry: {e}")

    return out


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_STOP = frozenset((
    "a an the of to in on for and or is are be it this that with as by at "
    "from not no when which there here never anywhere already just only "
    "again still also then now would could should been will can if so "
    "do does did has have had was were being am i you he she we they "
    "them their our your its his her these those such very more most "
    "than but yet while "
    # step-13/item-1: a short Russian function-word list (D-104's own
    # tokenizer is language-agnostic; without this, two unrelated Russian
    # findings sharing only "в"/"и"/"не"/"нет"/"это" plus one function name
    # scored 0.273 and merged).
    "в и не нет это на по за то что как от до или но же бы для с к у о из"
).split())
DEFAULT_MIN_SIMILARITY = 0.15

# step-12/F-4, widened step-13/item-1: shared review vocabulary that is too
# generic, on its own, to prove two findings are about the same defect.
# Re-checked against the real KLC-133/137/139 replay corpus (all 12 true
# pairs keep >= 9 shared tokens outside this set, comfortably over
# MIN_MEANINGFUL_SHARED below); re-check this list and the threshold again
# after ~10 more tickets carry a findings-pool.json (D-1xx).
_GENERIC_VOCAB = frozenset({"missing", "test", "unused", "used", "error", "handling",
                           "docstring", "validation", "function", "method", "check",
                           "checks", "covering", "exercises", "issue"})

# step-13/item-1: a title-only or near-title-length body routinely shares
# ONE generic-adjacent word by chance ("Missing docstring for parse()" vs
# "Missing validation in parse()" share only the function name "parse").
# Sharing a single such token is not enough evidence of the same defect;
# the reviewer's own measurement over KLC-110..153 found every real
# cross-reviewer duplicate shares at least 4 tokens outside the widened
# lists above, so 3 leaves margin without a single false merge observed.
MIN_MEANINGFUL_SHARED = 3


def _tokens(f: Finding) -> set[str]:
    """Lower-cased Unicode-word tokens (`\\w+`, so non-ASCII scripts such as
    Cyrillic score too, step-12/F-4) of title + first 200 chars of body,
    stop words dropped (D-104)."""
    text = f"{f.title} {f.body[:200]}".lower()
    return {t for t in _TOKEN_RE.findall(text) if t not in _STOP}


def _meaningful_overlap(a: Finding, b: Finding) -> bool:
    """step-12/F-4, threshold widened step-13/item-1: True iff a and b share
    at least `MIN_MEANINGFUL_SHARED` tokens that are not generic review
    vocabulary (`_GENERIC_VOCAB`) — a pure-generic overlap, or a single
    incidentally-shared word (e.g. one function name), is not evidence of
    the same defect no matter how high the resulting Jaccard score."""
    return len((_tokens(a) & _tokens(b)) - _GENERIC_VOCAB) >= MIN_MEANINGFUL_SHARED


def similarity(a: Finding, b: Finding) -> float:
    """Token-Jaccard over title + first 200 chars of body (AC-19)."""
    ta, tb = _tokens(a), _tokens(b)
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def _norm_path(p: str) -> str:
    """step-12/F-4: a repo-relative-ish normalisation for the same-file
    check — strip a leading './' only (paths are already repo-relative in
    practice); never raises."""
    p = (p or "").strip()
    return p[2:] if p.startswith("./") else p


def _basename(p: str) -> str:
    return p.rsplit("/", 1)[-1]


def min_similarity() -> float:
    """`review.dedupe.min_similarity` from config/reviewers.yml, falling back
    to DEFAULT_MIN_SIMILARITY on any read error or missing key (C-004/C-007).
    The repo's YAML reader returns scalars as strings, so this always casts."""
    import review_plan
    cfg, _note = review_plan.load_reviewers_cfg()
    value = (((cfg or {}).get("review") or {}).get("dedupe") or {}).get("min_similarity")
    try:
        return float(value) if value is not None else DEFAULT_MIN_SIMILARITY
    except (TypeError, ValueError):
        return DEFAULT_MIN_SIMILARITY


def group(items: list[Finding], min_sim: float) -> list[list[Finding]]:
    """Greedy, deterministic grouping (D-104): findings are visited in a
    stable order (severity rank, then reviewer, then original position);
    each joins the existing group with the highest similarity to any
    member, provided the group shares its file (step-12/F-4: a normalised-
    path match, or a bare basename matching the one distinct file it can
    unambiguously mean across this item set), holds no finding from the
    same `reviewer`, that similarity reaches `min_sim`, AND the pair shares
    at least `MIN_MEANINGFUL_SHARED` non-generic tokens (`_meaningful_overlap`,
    step-12/F-4, threshold widened step-13/item-1); otherwise it opens a new
    group. A group never holds two findings of one
    reviewer, so the visiting order also guarantees `group[0]` is always
    that group's highest-severity member (first by visit order on a tie,
    AC-19/D-105)."""
    norm = {id(f): _norm_path(f.file) for f in items}
    # Only FULL (slash-containing) paths are candidates a bare basename could
    # mean; a bare name matches iff exactly one full path shares its basename
    # across this item set (an ambiguous basename — two distinct full paths —
    # matches neither, and two distinct full paths never match each other
    # even when their basenames coincide).
    full_by_base: dict[str, set] = {}
    for n in norm.values():
        if "/" in n:
            full_by_base.setdefault(_basename(n), set()).add(n)

    def same_file(a: Finding, b: Finding) -> bool:
        na, nb = norm[id(a)], norm[id(b)]
        if na == nb:
            return True
        ba, bb = _basename(na), _basename(nb)
        if ba != bb:
            return False
        bare_a, bare_b = "/" not in na, "/" not in nb
        if bare_a == bare_b:
            return False
        return len(full_by_base.get(ba, ())) == 1

    order = sorted(range(len(items)),
                   key=lambda i: (_SEV_RANK.get(items[i].severity, 99), items[i].reviewer, i))
    groups: list[list[Finding]] = []
    for i in order:
        f = items[i]
        best, best_score = None, -1.0
        for g in groups:
            if not same_file(g[0], f) or any(m.reviewer == f.reviewer for m in g):
                continue
            score = max(similarity(f, m) for m in g)
            if (score >= min_sim - 1e-12 and score > best_score
                    and any(_meaningful_overlap(f, m) for m in g)):
                best, best_score = g, score
        if best is not None:
            best.append(f)
        else:
            groups.append([f])
    return groups


def _contributor(f: Finding) -> dict:
    return {"reviewer": f.reviewer, "kind": f.kind, "id": f.id, "title": f.title,
            "body": f.body, "severity": f.severity, "file": f.file, "line": f.line}


def _merge(group: list[Finding]) -> Finding:
    """A merged Finding per D-105: highest severity, and the rule_name,
    title, line, kind and fix of that highest-severity contributor (which is
    always group[0] — see `group()`'s own docstring); reviewer is the
    sorted, comma-joined contributor names; body is every contributor's
    "[reviewer] title" plus body, joined by "---". `issue_id` is
    recomputed fresh over every contributor's own issue_id, not copied from
    any one of them — the merged record's identity must never collide with
    (and so be confused for) a single contributor's, even when the
    contributor's own rule_name/file/line/id/kind/ref would otherwise hash
    identically (AC-19/AC-20's own "recomputed fresh" guarantee)."""
    best = group[0]
    reviewer = ", ".join(sorted({m.reviewer for m in group}))
    body = "\n\n---\n\n".join(f"[{m.reviewer}] {m.title}\n{m.body}" for m in group)
    merged = Finding(rule_name=best.rule_name, severity=best.severity, file=best.file,
                     line=best.line, title=best.title, body=body, fix=best.fix,
                     reviewer=reviewer, id=best.id, kind=best.kind, ref=best.ref, ac=best.ac)
    merged.issue_id = hashlib.sha1(
        "|".join(sorted(m.issue_id for m in group)).encode("utf-8")).hexdigest()[:12]
    return merged


def dedupe(findings: list[Finding], min_similarity: float | None = None) -> list[Finding]:
    """Collapse findings from different reviewers on the same file whose
    text similarity reaches the configured threshold (AC-19/AC-20). Never
    merges within one reviewer, across files, below the threshold, or
    because two findings happen to share an `issue_id`. Returns a new list;
    does not mutate input."""
    if not findings:
        return []
    thr = globals()["min_similarity"]() if min_similarity is None else min_similarity
    return [g[0] if len(g) == 1 else _merge(g) for g in group(findings, thr)]


# KLC-127 step-8: the review kinds a duplicate rate is measured over (AC-17).
# A plain tuple, not a handback.KINDS lookup — findings.py imports nothing
# from handback except lazily, inside the `pool` CLI branch (the ADR's one
# permitted file-level cycle).
REVIEW_KINDS = ("code-review", "external-review", "drift")


def build_pool(items: list[Finding], *, ticket: str, min_similarity: float) -> dict:
    """The whole `review/findings-pool.json` document (AC-17). Every kind's
    findings are pooled (deduplicated) into `findings[]`, each entry keeping
    every contributor in `contributors[]`; `raw_count`/`pooled_count`/
    `duplicate_rate` are computed over the review kinds only (`REVIEW_KINDS`)
    — a spec/test-plan/impl-plan finding is pooled but never counted in the
    numeric summary. `duplicate_rate` is `None` (JSON null), never `0`, when
    `raw_count` is 0 OR when fewer than two distinct reviewers contributed a
    review-kind finding (step-12/F-3): `group()` never merges two findings of
    one reviewer, so a single-reviewer ticket has a structural 0.0 duplicate
    rate that means nothing (there was no second opinion to agree or
    disagree with) and must not enter a track's mean as if it were a real
    measurement. `reviewers` names every distinct reviewer that contributed
    a review-kind finding, sorted, so a consumer can see WHY a rate is null."""
    groups = group(items, min_similarity)
    review_items = [f for f in items if f.kind in REVIEW_KINDS]
    raw = len(review_items)
    pooled = len(group(review_items, min_similarity)) if raw else 0
    reviewers = sorted({f.reviewer for f in review_items if f.reviewer})
    duplicate_rate = (1 - pooled / raw) if raw and len(reviewers) >= 2 else None
    return {
        "ticket": ticket,
        "min_similarity": min_similarity,
        "raw_count": raw,
        "pooled_count": pooled,
        "reviewers": reviewers,
        "duplicate_rate": duplicate_rate,
        "findings": [
            {**(g[0] if len(g) == 1 else _merge(g)).to_dict(),
             "contributors": [_contributor(m) for m in g]}
            for g in groups
        ],
    }


def sort_for_report(findings: list[Finding]) -> list[Finding]:
    """Sort findings for diff-friendly, human-readable reports.

    Order:
      1. File (lexicographic)
      2. Line (numeric ascending; a null line sorts before line 1)
      3. Severity (CRITICAL > HIGH > MEDIUM > LOW > INFO)

    Returns a new sorted list; does not mutate input.
    """
    def sort_key(f: Finding) -> tuple:
        return (f.file, -1 if f.line is None else f.line, _SEV_RANK.get(f.severity, 99))

    return sorted(findings, key=sort_key)


def main(argv=None):
    """CLI: `findings.py <partials-dir>` (unchanged) or
    `findings.py pool --ticket KEY` (KLC-127, AC-17)."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["pool"]:
        import handback  # noqa: E402  (lazy: the only findings -> handback edge, ADR)
        return handback.pool_main(argv[1:])

    if len(argv) < 1:
        print("Usage: findings.py <partials-dir>", file=sys.stderr)
        return 1

    partials = Path(argv[0])
    findings_list = aggregate(partials)
    findings_list = dedupe(findings_list)
    findings_list = sort_for_report(findings_list)

    print(json.dumps([f.to_dict() for f in findings_list], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
