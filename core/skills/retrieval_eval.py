#!/usr/bin/env python3
"""retrieval_eval.py — score the retriever at the integrate ack (KLC-110).

Closes the measurement loop that already has both of its ends built: a
retrieval trace is written for every ticket at intake (KLC-106), and the
committed diff is computable at integrate (`phase_completion._committed`).
This module is the missing middle — it compares the trace against the diff
and produces one record, persisted into `meta.json:metrics.retrieval` and
appended to the cross-ticket evidence log, so a *confidently wrong* retriever
becomes visible (a calibration failure) instead of silently absorbed into an
average.

Grown across KLC-110's build steps:
  - step-1: `load_planning_eval()` — the ONE canonical loader for KLC-108's
    `rank_metrics`, so this module and the corpus report never diverge into
    two scorer implementations (AC-1, D-210, D-213).
  - step-3: `evaluate()` — the pure record builder, four scored arrows and
    the degrade matrix (AC-2..AC-5, AC-11).
  - step-4: `consume()`/`append_log()`/`read_log()` — persistence through the
    ack's transaction and the derived evidence log (AC-8, AC-9, AC-16).
  - step-5: `advisory_records()` — the calibration advisory (AC-15).

Every scoring/classification/aggregation path in this module is
language-agnostic (AC-19): no file extension, no language name, no external
tool name.
"""
from __future__ import annotations

import sys
from pathlib import Path

_FILE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _FILE_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_FILE_DIR) not in sys.path:
    sys.path.insert(0, str(_FILE_DIR))

import test_conventions as _tc      # noqa: E402  (KLC-109: the shared test-path table)

_CANON = "planning_eval"        # the hyphen-named skill's canonical module name


def load_planning_eval():
    """THE one loader for the measurement skill (D-213, review F-2).

    `planning-eval.py` cannot be imported by name, and two independent
    `exec_module()` calls of the same file produce two distinct module
    objects and therefore two distinct `rank_metrics` objects. Registering
    under one canonical key in `sys.modules` makes identity hold by
    construction, so AC-1's "both call sites resolve to the same function
    object" is a constructible assertion rather than a hopeful one.
    """
    mod = sys.modules.get(_CANON)
    if mod is not None:
        return mod
    import importlib.util
    src = Path(__file__).resolve().parent / "planning-eval.py"
    spec = importlib.util.spec_from_file_location(_CANON, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_CANON] = mod           # register BEFORE exec: a partially
    spec.loader.exec_module(mod)        # initialised module is still the SAME object
    return mod


# The ONE scorer (D-210): both this module's evaluate() and the corpus
# report resolve to the identical `rank_metrics` object.
rank_metrics = load_planning_eval().rank_metrics


# --------------------------------------------------------------------------- #
# step-3: the evaluator record (AC-2..AC-5, AC-11)
# --------------------------------------------------------------------------- #
_UNAVAILABLE = "unavailable"
_TRACE_FIELDS = ("confidence", "mode", "degraded_inputs", "coverage_advisories")

# KLC-110 review round 1, step-9b (MEDIUM, AC-12, D-110-10): a malformed or
# runaway retrieval_trace.json must degrade, never balloon the read+parse
# cost the ack pays. The four candidate-list fields top out at 10 short
# paths each in a well-formed trace, so 512 KiB is generously larger than
# any real trace and small enough to bound even a pathological file.
_MAX_TRACE_BYTES = 512 * 1024

# The four candidate-list fields evaluate() scores. Each must be either
# absent/None or a list of strings — never a bare scalar or a list with a
# wrong-typed element (KLC-110 review round 1, step-9b, D-110-10).
_ARROW_FIELDS = ("files_likely_to_edit", "files_to_read_first",
                 "affected_modules_hint", "tests_to_read_or_run")


def read_trace(ticket: str) -> dict | None:
    """This ticket's own `retrieval_trace.json`, or None when absent,
    unreadable, or larger than `_MAX_TRACE_BYTES` (KLC-110 step-9b: the size
    guard degrades WITHOUT ever parsing the file). AC-21: the evaluator
    reads no index artifact other than the ticket's own trace and the
    module map (the module map is resolved upstream, in
    `phase_completion._committed`, not here)."""
    import json
    from core.shared.paths import klc_ticket_dir
    path = klc_ticket_dir(ticket) / "retrieval_trace.json"
    try:
        if path.stat().st_size > _MAX_TRACE_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _bad_arrow_field(trace: dict) -> str | None:
    """KLC-110 step-9b: the SPECIFIC reason a status:ok trace degrades when
    one of its scored candidate-list fields is wrong-typed — a bare scalar
    (e.g. an int) or a list containing a non-string element. Checked BEFORE
    any field reaches `rank_metrics`, whose own `c in t` / `set(topk)`
    arithmetic raises TypeError on exactly this input with no field name
    attached — the outer surface-only guard in phase_completion.py can then
    only report a generic 'degraded — TypeError' line. Returns None when
    every present field is well-typed (absent/None fields are fine — the
    existing empty-candidate convention, AC-6, handles those)."""
    for name in _ARROW_FIELDS:
        value = trace.get(name)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
            return f"trace field {name!r} is not a list of strings"
    return None


def _degraded(reason: str, trace: dict | None) -> dict:
    """AC-11: a stated reason and NOT ONE numeric metric. None of these cases
    may ever reach an aggregate as a zero."""
    rec = {"status": _UNAVAILABLE, "reason": reason,
           "trace_status": (trace or {}).get("status")}
    rec.update(_carried(trace))
    return rec


def _carried(trace: dict | None) -> dict:
    """The trace's own explanatory fields, read as the retriever reports them
    and never re-derived here (D-217). `coverage_advisories` is KLC-123's
    additive field: carried when present, omitted otherwise, so this ticket
    neither waits for nor blocks that one. There is no numeric `separation`
    in the trace, so the deciding reason is carried verbatim instead of being
    parsed (Q-210)."""
    out = {}
    for key in _TRACE_FIELDS:
        if (trace or {}).get(key) is not None:
            out[key] = trace[key]
    out.setdefault("confidence", "unknown")
    decided = [r for r in ((trace or {}).get("reasons") or []) if "confidence" in r]
    if decided:
        out["confidence_decided_by"] = decided[0]
    return out


def evaluate(trace: dict | None, committed_modules: set, committed_paths: set, *,
            modules_data: dict | None = None, ground_truth: dict | None = None) -> dict:
    """The record `_evaluate` builds, plus (KLC-128 D-209) a `ground_truth_source`
    field when *ground_truth* is given. `ground_truth` (a dict with `source` and
    `reason`, from `phase_completion.integrate_ground_truth`) is OPTIONAL and
    additive: with `None` (every caller before KLC-128) the record is
    byte-identical to before."""
    rec = _evaluate(trace, committed_modules, committed_paths, modules_data=modules_data,
                    empty_reason=(ground_truth or {}).get("reason"))
    if ground_truth is not None:
        rec["ground_truth_source"] = ground_truth.get("source")
    return rec


def _evaluate(trace: dict | None, committed_modules: set, committed_paths: set, *,
             modules_data: dict | None = None, empty_reason: str | None = None) -> dict:
    """Build the record. PURE: no git, no file read, no file write — the
    ground truth arrives already computed by the ack (AC-7, AC-21, D-215).
    `modules_data` (KLC-110 review round 1, step-10, D-110-11) is the SAME
    parsed modules.json this ack has already loaded — an OPTIONAL, additive
    parameter: still no read of its own, it is DATA IN, exactly like
    `committed_modules`/`committed_paths`. `empty_reason` (KLC-128 D-209): the
    ground-truth resolver's OWN named reason for an empty `committed_paths`
    (e.g. 'no recorded pre-merge range for this ticket'), used in place of the
    generic message below when given."""
    if not trace:
        return _degraded("no retrieval trace for this ticket", None)
    if trace.get("status") != "ok":
        return _degraded(f"trace status is {trace.get('status')!r}", trace)
    _bad_field = _bad_arrow_field(trace)
    if _bad_field:
        return _degraded(_bad_field, trace)
    if not committed_paths:
        return _degraded(empty_reason or "no committed diff after the lifecycle-path exclusion", trace)

    score = load_planning_eval().rank_metrics       # the ONE scorer (D-210)
    truth = set(committed_paths)
    # The ONE test-path predicate (AC-4, D-302). `table=None` is the DEFAULT,
    # the shipped built-in table — deliberately NOT `active_table()`: the
    # evaluator has no other reason to resolve a profile manifest, and a
    # profile-dependent classification would make this arrow's score depend
    # on repo configuration, which is what AC-19's language-agnostic clause
    # is about not doing. `exists=` is REQUIRED by KLC-109's own consumer
    # discipline (tests/integration/test_klc109_guard.py::
    # test_every_consumer_call_passes_exists — every is_test_path()/
    # test_signal() call site outside test_conventions.py itself must pass
    # exists=, on pain of the conservative default silently starving a
    # basename-only match).
    #
    # KLC-110 review round 1, step-10 (MEDIUM, AC-4, D-110-11 — SUPERSEDED by
    # D-110-14, review round 2, step-12): membership in the COMMITTED DIFF
    # ALONE under-confirmed a colocated name-signal test changed WITHOUT its
    # untouched production sibling (the ordinary shape of a lone
    # `foo_test.py` commit) — the sibling is real, just not part of THIS
    # diff. `_sibling_known` widens the predicate to ALSO accept membership
    # in the module map's known file universe (AC-21 explicitly sanctions
    # reading it).
    #
    # D-110-14 (round 2, step-12): step-10's first attempt used
    # `module_membership.file_to_module(...).get("resolution_source") !=
    # "orphan"` — but for a DIRECTORY-BOUNDARY module (`path` ending in
    # `/`, e.g. `core/skills/`), file_to_module resolves ANY same-directory
    # path non-orphan via prefix matching, whether or not that exact file
    # exists. Reproduced against the LIVE modules.json:
    # `core/skills/test_conventions.py` (a real PRODUCTION file, matching
    # the `test_*.py` NAME-signal glob) derives the fictional sibling
    # `core/skills/conventions.py`, which resolves non-orphan under
    # directory-prefix residency purely because it sits under
    # `core/skills/` — exactly the self-collision `test_conventions.py`'s
    # own module docstring built `exists=` to prevent (KLC-109 D-109-9).
    # `_module_map_files` fixes this by checking LITERAL membership in the
    # module map's own PER-FILE listings — each module entry in
    # modules.json carries a real `files` array (a genuine enumeration, not
    # a prefix pattern), unioned with the small top-level `files` override
    # map's keys — never directory-prefix residency. `modules_data` is
    # still the SAME parsed modules.json already loaded this ack
    # (D-216-style reuse, see `phase_completion._modules_data_cached`), so
    # this costs nothing beyond what the ack already pays — zero extra I/O,
    # zero extra git calls either way. `modules_data` omitted (every caller
    # before step-10, and any future caller that does not have it handy)
    # falls back to the ORIGINAL diff-only check — additive, not a
    # behaviour change for an unmigrated caller.
    def _module_map_files(data: dict) -> frozenset:
        out: set = set()
        for m in (data or {}).get("modules") or []:
            out.update(m.get("files") or [])
        out.update((data or {}).get("files") or {})
        return frozenset(out)

    _known_files = _module_map_files(modules_data) if modules_data else frozenset()

    def _sibling_known(cand: str) -> bool:
        if cand in truth:
            return True
        return cand in _known_files

    test_truth = {p for p in truth if _tc.is_test_path(p, exists=_sibling_known)}
    hint_truth = set(committed_modules)

    # KLC-110 review round 1, step-8 (HIGH, AC-5, D-110-8): `affected_modules_hint`
    # is an ALPHABETICALLY SORTED, UNRANKED, UNCAPPED set — unlike the two
    # edit/read arrows, which the retriever itself truncates to 5/10 — so
    # capping k to len(hint_truth) (the pre-fix behaviour) silently truncated
    # the CANDIDATE list to the size of the TRUTH set, letting a hint far
    # larger than the truth score a false-perfect precision while `is_subset`
    # correctly read False in the very same record (repro: hint [a,b,c,z],
    # truth {a} -> precision 1.0, extra [] pre-fix; 0.25, extra [b,c,z]
    # post-fix). Scoring it UNCAPPED (k = len(hint) or 1) means nothing in
    # the hint is ever truncated, through the SAME one scorer (AC-1 guard) —
    # this is a k-argument correction, not a second scorer.
    _hint_candidates = trace.get("affected_modules_hint") or []
    rec = {"status": "ok", "trace_status": trace.get("status"),
           "ground_truth_files": len(truth),
           "ground_truth_modules": sorted(hint_truth),
           "files_likely_to_edit": score(trace.get("files_likely_to_edit"), truth, 5),
           "files_to_read_first": score(trace.get("files_to_read_first"), truth, 10),
           "affected_modules_hint": score(_hint_candidates,
                                          hint_truth, len(_hint_candidates) or 1)}
    rec.update(_carried(trace))
    hint = set(trace.get("affected_modules_hint") or [])
    rec["affected_modules_hint"]["is_subset"] = hint <= hint_truth
    rec["affected_modules_hint"]["is_superset"] = hint >= hint_truth
    rec["tests_to_read_or_run"] = (
        score(trace.get("tests_to_read_or_run"), test_truth, len(test_truth) or 1)
        if test_truth else
        {"status": _UNAVAILABLE,
         "reason": "the diff contains no test file, so this arrow has no ground truth"})
    return rec


# --------------------------------------------------------------------------- #
# step-4: persistence through the ack transaction, and the derived evidence
# log (AC-8, AC-9, AC-16)
# --------------------------------------------------------------------------- #
def consume(ticket, trace, committed_modules, committed_paths, track, *, persist,
           modules_data: dict | None = None, ground_truth: dict | None = None):
    """Build the record and, on the PERSISTING path only, stage and log it.

    Returns the record; the caller turns it into advisory records. A
    read-only probe computes exactly the same record and stages NOTHING,
    appends NOTHING and writes NOTHING (AC-10, D-222). `modules_data`
    (KLC-110 step-10) is threaded straight through to `evaluate()`.
    `ground_truth` (KLC-128 D-209) is threaded straight through too."""
    rec = evaluate(trace, committed_modules, committed_paths, modules_data=modules_data,
                  ground_truth=ground_truth)
    if persist:
        import lifecycle as _lc
        _lc.stage_meta_patch(ticket, {"metrics": {"retrieval": rec}})
        append_log(ticket, track, rec)
    return rec


def append_log(ticket, track, rec):
    """One JSON object per line (AC-9). Append-only: a repeated ack writes a
    second physical line and `read_log()` supersedes by ticket key, so no
    aggregate counts one ticket twice and no reader needs a rewrite path. A
    surplus line left by a rolled-back push is harmless for the same reason
    — the authoritative record is the per-ticket one in meta.json, and this
    file is derived (AC-16)."""
    import json
    from datetime import datetime, timezone
    from core.shared.paths import klc_knowledge_dir
    row = dict(rec)
    row.update({"ticket": ticket, "track": track,
                "logged_at": datetime.now(timezone.utc)
                                     .strftime("%Y-%m-%dT%H:%M:%SZ")})
    path = klc_knowledge_dir() / "retrieval-eval.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass          # AC-12: an unwritable derived cache never touches the ack


def _log_lines():
    from core.shared.paths import klc_knowledge_dir
    path = klc_knowledge_dir() / "retrieval-eval.jsonl"
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def read_log():
    """Ticket key -> its LAST logged row. Superseding on read is the whole
    of AC-9's no-double-count guarantee; an unreadable line is skipped,
    never raised, because this file is a derived cache and not a source of
    truth."""
    import json
    rows = {}
    for line in _log_lines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("ticket"):
            rows[row["ticket"]] = row
    return rows


# --------------------------------------------------------------------------- #
# step-5: the calibration advisory (AC-15)
# --------------------------------------------------------------------------- #
def advisory_records(ticket, rec):
    """AC-15: EXACTLY ONE record, and only for a confidently wrong answer. A
    wrong answer given tentatively is not a calibration failure and stays
    silent (D-220). `medium` when the retriever named files and hit none;
    `info` when it named no file at all, which is a thinner signal."""
    if rec.get("status") != "ok" or rec.get("confidence") not in ("medium", "high"):
        return []
    edit = rec.get("files_likely_to_edit") or {}
    if not edit.get("candidates"):
        return [{"source": "retrieval-eval", "severity": "info",
                 "code": "retrieval-eval.no-edit-candidates",
                 "message": (f"retrieval calibration: {ticket} traced at confidence "
                             f"{rec['confidence']} but named no file it might edit — "
                             f"the index is likely degraded, run `klc doctor`"),
                 "ref": ticket}]
    if edit.get("precision"):
        return []
    return [{"source": "retrieval-eval", "severity": "medium",
             "code": "retrieval-eval.zero-precision",
             "message": (f"retrieval calibration: {ticket} traced at confidence "
                         f"{rec['confidence']} but none of the files it named were "
                         f"changed — the index is likely degraded, run `klc doctor`"),
             "ref": ticket}]
