---
ticket: KLC-117
phase: design
track: M
kind: tech
authority: agent
option: A
adr: design/adr.md
last_generated: 2026-09-17T00:45:00Z
---

# KLC-117 — implementation plan

Eight steps, each one logical commit, implementing option A from
`design/options.md`. The order is chosen so that the schema and its degradation
paths exist and are tested before anything depends on them, and so that every
commit leaves the suite green — a concurrent build agent is working the same tree
on `feature/klc-118-card-modes`, so no step may leave a broken intermediate.

**Standing rules for this plan.**

1. Run only the test files a step's `VERIFY` names. Do not run the full suite;
   another ticket is building in this tree.
2. `PROJECT_ROOT=/home/ek/projects/klc` on every command (CLAUDE.md).
3. Degrade-not-fail is absolute (C-001). No function added by this plan may
   raise out of the advisory path, and none may turn a completable phase into a
   blocked one. Every new entry point gets a guard, and the guard gets a test.
4. `persist=False` writes nothing (C-002). Any step that adds a write must state
   where the `persist` flag gates it.
5. This plan edits no file under `core/agents/` and no `VERB_SPECS` entry, so
   `core/skills/plugin_gen.py` is **not** run. The single `klc-plugin/` file it
   touches is the handwritten, presence-guarded `skills/run/SKILL.md`
   (`core/skills/plugin_gen.py:101`), which the generator never overwrites
   (design D-007).

**Deviation from a naive one-file-per-step reading of the test plan.** Two rows
of `test-plan.md` name tests whose assertion is stated at the `can_complete`
level — `test_klc117_summary_line.py::test_empty_advisory_result_when_no_producer_emits`
and `test_klc117_producer_degrade.py::test_raising_producer_degrades_to_single_info_record`.
They are written in step-3, where the gate actually routes through the
aggregator, not in step-1 where the rest of their file lives. Every other test
name in `test-plan.md` is written in the step that owns its behaviour, and no
test name appears in two steps.

- [x] step-1 done — `core/skills/advisories.py` created; 5 passed as expected.
- [x] step-2 done — producers emit records; 1 passed + 167 passed (baseline,
  see D-103 for the `test_phase_completion_drift.py` deferral to step-3).
- [x] step-3 done — gate persists records + summary; 13 passed + 29 passed
  (exact Expected). See D-104 for the wider assertion-repair sweep this step
  actually required (record-shaped twins + 8 test-file fixes across the tree).
- [x] step-4 done — `advisories.cap_note` wired into `core/phases/ack.py`;
  2 passed (exact Expected).
- [x] step-5 done — `settings.advisory_threshold`, `validate_config` schema entry,
  `gate_policy._advisory_clean` reading `advisories.read` per D-102; 7 passed +
  27 passed (exact Expected). `tests/integration/test_gate_policy.py`'s and
  `tests/integration/test_autorunner.py`'s `_CLEAN_SIG(NALS)` fixtures updated
  from `"advisory": ""` to the new dict shape (mechanical, not a logic change).
- [x] step-6 done — `advisories.for_display`, wired into `status.py`/`work.py`
  (JSON + human render) and `klc-plugin/skills/run/SKILL.md` loop step 6;
  4 passed + 19 passed (exact Expected); `test_plugin_agents_in_sync.py`
  (bespoke-skill presence guard) still 12 passed.
- [x] step-7 done — `core/phases/migrate_notes.py` (D-101's acquire_lock +
  state_tx envelope), `scripts/klc` dispatch entry; 4 passed (exact Expected).
  `pg._LIFECYCLE_CMDS` (plugin_gen.py) intentionally untouched, per the plan's
  own standing rule 5 (no `core/agents/` or `VERB_SPECS` edit in this ticket).
- [x] step-8 done — `docs/process.md`: "Ack advisories" subsection, seven-signal
  table row updated, `migrate-notes` added to `## Verbs`, independent-review
  section notes routed decisions arrive as `high` records; `config/settings.yml`
  already documented the knob at step-5. `1 passed` + `settings ok` (exact
  Expected). All 8 steps complete.

## step-1 — the record schema, the aggregator and its degradation paths

- Goal: `core/skills/advisories.py` exists and can normalise a mixed list of
  producer outputs into severity-bearing records, render the one-line summary,
  and degrade a bare string, a malformed record or an unknown severity into a
  visible `info` record — with nothing wired into the gate yet.
- RED: `tests/integration/test_klc117_severity_normalisation.py::test_unknown_severity_normalised_to_info_and_flagged`,
  `::test_missing_severity_field_defaults_to_info_and_flagged`,
  `tests/integration/test_klc117_producer_degrade.py::test_bare_string_producer_wrapped_as_legacy_string_info_record`,
  `::test_record_missing_required_keys_degrades_to_info`, and
  `tests/integration/test_klc117_summary_line.py::test_summary_counts_and_path_when_records_exist`
  (test-plan rows for AC-3, AC-6 and the AC-1 negative twin) — all five fail
  because the module does not exist.
- GREEN: create `core/skills/advisories.py` with `SEVERITIES`, `SEVERITY_ORDER`,
  `NOTE_CAP`, `normalise_record`, `collect`, `render_summary` and
  `at_or_above`. `collect` takes `(source, items)` pairs, accepts a `list[dict]`
  or a bare `list[str]` per source, wraps a bare string as one
  `info` / `legacy-string` record, and catches every exception per source into
  one `info` / `producer-raised` record. No caller yet.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_severity_normalisation.py tests/integration/test_klc117_producer_degrade.py tests/integration/test_klc117_summary_line.py -q`
- Expected: `5 passed`.
- COMMIT: KLC-117 step-1: advisory record schema, aggregator and degradation paths
- Affected: `core/skills/advisories.py` (new),
  `tests/integration/test_klc117_severity_normalisation.py` (new),
  `tests/integration/test_klc117_producer_degrade.py` (new),
  `tests/integration/test_klc117_summary_line.py` (new).
- Addresses: AC-3, AC-6, AC-7, AC-18
- Interfaces: `advisories.SEVERITIES` (tuple), `advisories.NOTE_CAP` (int, 200),
  `advisories.normalise_record(source, raw) -> tuple[dict, dict | None]` (new),
  `advisories.collect(sources) -> list[dict]` (new),
  `advisories.render_summary(records, artifact_rel) -> str` (new),
  `advisories.at_or_above(records, threshold) -> bool` (new).
- Depends on: none
- Code sketch:

```python
# core/skills/advisories.py
"""advisories.py — the one advisory aggregator for the phase-completion gate.

Owns the record schema, the severity vocabulary, collection from every producer,
the artifact write and the summary line. Producers emit plain dicts and import
nothing from here (design D-002), so a malformed record is a real runtime case
with a real test rather than an impossible type error.
"""
from __future__ import annotations

SEVERITIES = ("high", "medium", "low", "info")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}
NOTE_CAP = 200          # characters, a data-hygiene invariant, not a knob (Q-004)
_REQUIRED = ("source", "severity", "code", "message", "ref")


def normalise_record(source: str, raw) -> tuple[dict, dict | None]:
    """One well-formed record, plus a companion flag record when `raw` was bad.

    A bare string becomes info/legacy-string (AC-18: no silent forwarding of an
    untyped producer output). A missing or unknown severity becomes info AND
    raises a flag naming the offender, so the mis-declaration is visible (AC-3).
    """
    if isinstance(raw, str):
        return ({"source": source, "severity": "info", "code": "legacy-string",
                 "message": raw, "ref": ""}, None)
    if not isinstance(raw, dict) or not str(raw.get("message", "")).strip():
        return ({"source": source, "severity": "info", "code": "malformed-record",
                 "message": f"{source}: emitted a malformed advisory record",
                 "ref": repr(raw)[:120]}, None)
    rec = {k: str(raw.get(k, "") or "") for k in _REQUIRED}
    rec["source"] = rec["source"] or source
    rec["code"] = rec["code"] or f"{rec['source']}.unspecified"
    sev = rec["severity"]
    if sev in SEVERITIES:
        return rec, None
    rec["severity"] = "info"
    flag = {"source": source, "severity": "info", "code": "malformed-record",
            "message": (f"{source}: record {rec['code']} declared severity "
                        f"{sev!r}, which is not one of {'/'.join(SEVERITIES)}; "
                        f"normalised to info"),
            "ref": rec["code"]}
    return rec, flag


def collect(sources) -> list[dict]:
    """Normalise every producer's output. `sources` is an iterable of
    (source_name, callable_or_iterable). A producer that raises degrades to one
    info/producer-raised record; nothing here ever propagates (C-001)."""
    out: list[dict] = []
    for source, items in sources:
        try:
            items = items() if callable(items) else items
            for raw in (items or []):
                rec, flag = normalise_record(source, raw)
                out.append(rec)
                if flag:
                    out.append(flag)
        except Exception as exc:                       # noqa: BLE001
            out.append({"source": source, "severity": "info",
                        "code": "producer-raised",
                        "message": (f"{source}: advisory producer did not run — "
                                    f"{type(exc).__name__} (unverified)"),
                        "ref": ""})
    out.sort(key=lambda r: (SEVERITY_ORDER[r["severity"]], r["source"], r["code"]))
    return out


def render_summary(records, artifact_rel: str) -> str:
    """`2 high · 3 medium · 11 info — see <path>`; empty string for no records.

    high and medium are ALWAYS rendered so an operator can read `0 high ·
    0 medium` and stop; low and info appear only when non-zero (design D-003,
    reconciling the two summary strings test-plan.md pins for AC-6 and AC-17).
    """
    if not records:
        return ""
    counts = {s: sum(1 for r in records if r["severity"] == s) for s in SEVERITIES}
    parts = [f"{counts[s]} {s}" for s in SEVERITIES
             if s in ("high", "medium") or counts[s]]
    return " · ".join(parts) + f" — see {artifact_rel}"


def at_or_above(records, threshold: str) -> bool:
    """True when any record is at or above `threshold` in severity."""
    limit = SEVERITY_ORDER.get(threshold, SEVERITY_ORDER["medium"])
    return any(SEVERITY_ORDER[r["severity"]] <= limit for r in records)
```

> [!DECISION D-103] owner=impl-agent date=2026-09-17T00:00:00Z refs=step-2
> The plan's step-2 GREEN converts `phase_completion._drift_advisories` and
> `_drift_review_advisories` to return records. `_drift_review_advisories`
> delegates to the `drift_review` seam, which only exposed a string-returning
> `consume`; converting the call site required a record-shaped twin, so a
> `drift_review.consume_records` wrapper (mirroring its existing `consume`,
> itself a thin delegate to `spec_review.consume_records`) was added — a small,
> in-module (`core/skills`, already an affected module) addition not itemised
> in step-2's Affected list but required for the conversion to type-check and
> to keep `_can_complete_generic`'s six-site string-join (still literal code in
> this commit) fed with real strings via `r["message"]`. Two tests in
> `tests/test_drift_review.py` (`test_integrate_surfaces_drift_review_decisions`,
> `test_records_findings_only_on_persist`) monkeypatched the old `consume` name
> and were updated to monkeypatch `consume_records` with record-shaped fixtures;
> this is the kind of assertion-on-old-shape edit step-3's own VERIFY text
> anticipates, applied one step early to avoid a longer-lived silent regression.
> `tests/test_phase_completion_drift.py` (6 tests) now fails because
> `_drift_advisories` returns records instead of strings — left unfixed here
> exactly as step-3's VERIFY text sanctions ("any assertion there that pins
> the OLD joined-prose success message is updated ... in step-3"); fixed in
> step-3's own commit.

## step-2 — every producer emits structured records

- Goal: the four producer modules and the two drift arms each expose a function
  returning record dicts whose severity is declared next to the check that knows
  the condition, while every existing `warn_lines` and `consume` keeps its
  current contract byte-for-byte.
- RED: `tests/integration/test_klc117_producer_records.py::test_producers_emit_structured_records`
  (test-plan AC-1 row) — drives `spec_selfcheck` and `ac_test_coverage` through
  `advisories.collect` over a fixture ticket and asserts every collected item is
  a dict carrying all five fields; fails because no producer has the function.
- GREEN: add `advisory_records` to `spec_selfcheck.py`, `ac_test_coverage.py` and
  `testplan_review.py`, each with a module-local `_SEVERITY` table keyed on its
  own condition vocabulary; add `consume_records` to `spec_review.py` and make
  the existing `consume` a thin renderer over it so its `(list[str], findings)`
  return is unchanged; convert `phase_completion._drift_advisories` and
  `_drift_review_advisories` to return records. Wire nothing into the gate yet —
  the six string-joining sites still run in this commit.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_producer_records.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/test_spec_selfcheck.py tests/test_ac_test_coverage.py tests/test_testplan_review.py tests/test_spec_review.py tests/test_klc094_implplan_review.py tests/test_drift_review.py -q`
- Expected: `1 passed` from the first command. The second reports no failures
  over the six unmodified producer and seam modules (161 test functions before
  `test_ac_test_coverage.py`'s 13 `parametrize` expansions); record its exact
  collected count in `build-log.md` as the baseline for later steps.
- COMMIT: KLC-117 step-2: producers emit severity-bearing advisory records
- Affected: `core/skills/spec_selfcheck.py`, `core/skills/ac_test_coverage.py`,
  `core/skills/testplan_review.py`, `core/skills/spec_review.py`,
  `core/skills/phase_completion.py`,
  `tests/integration/test_klc117_producer_records.py` (new).
- Addresses: AC-1
- Interfaces: `spec_selfcheck.advisory_records(report) -> list[dict]` (new),
  `ac_test_coverage.advisory_records(report) -> list[dict]` (new),
  `testplan_review.advisory_records(report) -> list[dict]` (new),
  `spec_review.consume_records(ticket_dir, track, signals=None, kind=SPEC_REVIEW, persist=True) -> tuple[list[dict], list[dict]]`
  (new). Unchanged: `spec_selfcheck.warn_lines`, `ac_test_coverage.warn_lines`,
  `testplan_review.warn_lines`, `spec_review.consume`,
  `spec_review.route_decisions`, `spec_review.summarize_findings`.
- Depends on: step-1
- Code sketch:

```python
# core/skills/spec_selfcheck.py — severity lives HERE, next to the condition (C-003)
_SEVERITY = {"markers-deferred": "medium"}   # every other dimension is info


def advisory_records(report) -> list[dict]:
    """The KLC-117 record form of `warn_lines`. Same conditions, same wording,
    a typed carrier. `warn_lines` stays for this module's own tests and CLI."""
    out = []
    for f in report.surfaced:
        if f.dimension == "constitution":
            continue
        code = f"spec-self-check.{f.dimension}"
        out.append({"source": "spec-self-check",
                    "severity": _SEVERITY.get(f.dimension, "info"),
                    "code": code, "message": f.message, "ref": f.dimension})
    con = [f for f in report.surfaced if f.dimension == "constitution"]
    if con:
        n = len(report.constitution_checklist)
        out.append({"source": "spec-self-check", "severity": "info",
                    "code": "spec-self-check.constitution",
                    "message": (f"{n} review-principle(s) to consider "
                                f"(run spec_selfcheck for the checklist)"
                                if n else con[0].message),
                    "ref": "constitution"})
    return out


# core/skills/spec_review.py — the seam: records first, lines derived from them.
def consume_records(ticket_dir, track, signals=None, kind=SPEC_REVIEW,
                    persist: bool = True):
    """Record-shaped twin of `consume`. A routed decision and a findings set
    containing a high finding are HIGH; schema notes, degradation and an absent
    expected review are MEDIUM (Q-003 table, design/options.md)."""
    # same body as consume(), emitting dicts instead of f-strings; `persist`
    # still gates record_findings exactly as today (C-002).


def consume(ticket_dir, track, signals=None, kind=SPEC_REVIEW, persist=True):
    """UNCHANGED contract: (list[str], findings). Now a renderer over
    consume_records, so the 85 assertions in the four review-binding test
    modules keep passing unmodified."""
    records, findings = consume_records(ticket_dir, track, signals, kind, persist)
    return [r["message"] for r in records], findings
```

## step-3 — the gate writes the artifact and returns the summary

- Goal: all six `can_complete_*` success returns route through the one
  aggregator, which writes `<ticket_dir>/<phase>/ack-advisories.json` on the
  persisting path, writes nothing on a probe, and returns the one-line summary in
  place of the joined string.
- RED: `tests/integration/test_klc117_artifact_write.py::test_persisting_ack_writes_ack_advisories_json`,
  `::test_probe_persist_false_writes_no_file`,
  `::test_unwritable_artifact_path_degrades_without_raising`,
  `tests/integration/test_klc117_aggregator_single_path.py::test_no_second_string_join_path_remains_on_success`,
  `::test_probe_and_persisting_calls_share_one_aggregator`,
  plus the two gate-level rows deferred from step-1,
  `tests/integration/test_klc117_summary_line.py::test_empty_advisory_result_when_no_producer_emits`
  and `tests/integration/test_klc117_producer_degrade.py::test_raising_producer_degrades_to_single_info_record`
  (test-plan rows for AC-2, AC-4, AC-5, AC-7, AC-18 and the unwritable-path edge
  case) — all seven fail because the gate still joins strings.
- GREEN: add `advisories.finish(ticket, phase_id, sources, persist)` returning
  `(records, summary)`; it collects, writes the artifact when `persist` is true,
  and swallows an `OSError` on the write into one `info` record. Replace each of
  the six `"; ".join` success returns with a `finish` call. Add
  `advisories.read(ticket, phase_id)` for the later consumers.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_artifact_write.py tests/integration/test_klc117_aggregator_single_path.py tests/integration/test_klc117_summary_line.py tests/integration/test_klc117_producer_degrade.py tests/integration/test_klc117_producer_records.py tests/integration/test_klc117_severity_normalisation.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_spec_review_gate.py tests/integration/test_testplan_coverage_gate.py tests/test_phase_completion_drift.py -q`
- Expected: `13 passed` from the first command (the eight tests from steps 1–2
  plus five of the seven new ones; the other two live in the files already
  listed). The second command covers the three gate-level regression modules
  (29 test functions) and must report no failures; any assertion there that pins
  the OLD joined-prose success message is updated to expect the summary line, and
  each such edit is listed in `build-log.md`.
- COMMIT: KLC-117 step-3: gate persists advisory records and returns a summary line
- Affected: `core/skills/advisories.py`, `core/skills/phase_completion.py`,
  `tests/integration/test_klc117_artifact_write.py` (new),
  `tests/integration/test_klc117_aggregator_single_path.py` (new),
  `tests/integration/test_klc117_summary_line.py`,
  `tests/integration/test_klc117_producer_degrade.py`.
- Addresses: AC-2, AC-4, AC-5
- Interfaces: `advisories.SCHEMA_VERSION` (int),
  `advisories.artifact_path(ticket, phase_id) -> Path` (new),
  `advisories.finish(ticket, phase_id, sources, persist=True) -> tuple[list[dict], str]`
  (new), `advisories.read(ticket, phase_id) -> dict | None` (new). Unchanged:
  `phase_completion.can_complete` and the five `can_complete_*` entry points keep
  their `(bool, str)` signatures.
- Depends on: step-2
- Code sketch:

```python
# core/skills/advisories.py (added in this step)
import json
from datetime import datetime, timezone
from pathlib import Path
from core.shared.paths import klc_ticket_meta_file, project_root

SCHEMA_VERSION = 1
ARTIFACT_NAME = "ack-advisories.json"


def artifact_path(ticket: str, phase_id: str) -> Path:
    return klc_ticket_meta_file(ticket).parent / phase_id / ARTIFACT_NAME


def finish(ticket: str, phase_id: str, sources, persist: bool = True):
    """Collect, persist (ack path only) and render. Returns (records, summary).

    C-002: when `persist` is False NOTHING is written — the probe path used by
    `klc remind` and gate-policy signal collection must stay write-free, so the
    mkdir and the write both sit inside the flag.
    """
    records = collect(sources)
    path = artifact_path(ticket, phase_id)
    try:
        rel = str(path.relative_to(project_root()))
    except ValueError:
        rel = str(path)
    if persist and records:
        envelope = {"schema_version": SCHEMA_VERSION, "ticket": ticket,
                    "phase": phase_id,
                    "generated_at": datetime.now(timezone.utc)
                                            .strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "records": records}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False)
                            + "\n", encoding="utf-8")
        except OSError as exc:                         # C-001: never block an ack
            records.append({"source": "advisories", "severity": "info",
                            "code": "malformed-record",
                            "message": (f"advisory artifact not written — "
                                        f"{type(exc).__name__}"), "ref": rel})
    return records, render_summary(records, rel)


def read(ticket: str, phase_id: str):
    """The persisted envelope, or None when absent/unreadable. Never raises."""
    try:
        return json.loads(artifact_path(ticket, phase_id).read_text("utf-8"))
    except Exception:                                  # noqa: BLE001
        return None
```

And the call site itself, repeated at each of the six success returns:

```python
# core/skills/phase_completion.py — each of the six sites, e.g. :211-212
import advisories as _adv                              # module-level import

    _sources = [("spec-self-check", _spec_warning_records),
                ("discovery", _decompose_records(spec_text)),
                ("spec-review", lambda: _spec_review_records(ticket, persist))]
    _records, _summary = _adv.finish(ticket, "discovery", _sources, persist)
    return True, _summary
```

> [!DECISION D-104] owner=impl-agent date=2026-09-17T00:00:00Z refs=step-3
> Step-3's Affected list names only `core/skills/advisories.py`,
> `core/skills/phase_completion.py` and the four `test_klc117_*` files. In
> practice, converting the six success sites to route through
> `advisories.finish` changed the CONTENT of every affected phase's returned
> string (from joined prose to a one-line summary), which is a real behaviour
> change for every existing test that asserted on that content. This required:
> (1) new record-shaped twins `_spec_review_records` / `_testplan_review_records`
> / `_implplan_review_records` in `phase_completion.py` (the existing
> `_spec_review_advisories` / `_testplan_review_advisories` /
> `_implplan_review_advisories` stay untouched, list[str]-returning, because
> `tests/test_klc094_implplan_review.py` calls the impl-plan one directly and
> pins its `list[str]` shape) — each new twin calls a `consume_records` sibling
> added to `spec_review.py` (step-2), `testplan_review.py` and
> `implplan_review.py` (both additive, mirroring `drift_review.consume_records`
> from step-2/D-103); (2) fixing every test whose assertion pinned the OLD
> joined-prose success string to instead read `advisories.read(ticket, phase_id)`
> and assert on record content — beyond the three modules step-3's own VERIFY
> names (`test_spec_review_gate.py`, `test_testplan_coverage_gate.py`,
> `test_phase_completion_drift.py`), this also touched
> `tests/test_ac_test_coverage.py` (3 tests), `tests/integration/test_socratic_gate.py`
> (3 tests), `tests/integration/test_spec_quality_gate.py` (1 test) and
> `tests/test_drift_review.py` (1 test, persist flipped to True to read the
> artifact). All edits are additive-assertion-only (no test's INTENT changed,
> only how it reads the now-relocated advisory content), matching the
> plan's own step-3 text: "any assertion there that pins the OLD joined-prose
> success message is updated to expect the summary line." No file outside
> `core/skills`/`tests` was touched, so this stays within `meta.json:affected_modules`.

## step-4 — the ack note is capped at 200 characters

- Goal: the manual-completion transition writes a note of at most 200 characters
  that ends with the summary line, and the KLC-105 fixture reproduces at that
  size with all twelve records intact in the artifact.
- RED: `tests/integration/test_klc117_ack_note_cap.py::test_note_within_cap_for_manual_completion_ack`
  and `tests/integration/test_klc117_klc105_fixture_replay.py::test_klc105_build_ack_note_shrinks_to_cap_with_all_12_records_present`
  (test-plan rows for AC-8 and AC-17) — both fail because `ack.py` still
  concatenates the whole advisory onto the base note.
- GREEN: add `advisories.cap_note(base, summary)` and call it from
  `core/phases/ack.py:100-102`. `lifecycle.set_state` is not touched: it keeps
  storing verbatim whatever note it is handed, which is what the test-plan's
  regression section requires.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_ack_note_cap.py tests/integration/test_klc117_klc105_fixture_replay.py -q`
- Expected: `2 passed`.
- COMMIT: KLC-117 step-4: cap the phase-history note at 200 characters
- Affected: `core/skills/advisories.py`, `core/phases/ack.py`,
  `tests/integration/test_klc117_ack_note_cap.py` (new),
  `tests/integration/test_klc117_klc105_fixture_replay.py` (new).
- Addresses: AC-8, AC-17
- Interfaces: `advisories.cap_note(base, summary, cap=NOTE_CAP) -> str` (new).
  `lifecycle.set_state` unchanged.
- Depends on: step-3
- Code sketch:

```python
# core/skills/advisories.py
_ELLIPSIS = "…"


def cap_note(base: str, summary: str, cap: int = NOTE_CAP) -> str:
    """`base; summary`, at most `cap` CHARACTERS, with the summary kept intact.

    The summary carries the artifact pointer, so it is the part that must
    survive: when the pair does not fit, the BASE is shortened, never the
    summary. A pathologically long summary (a very deep artifact path) is
    trimmed from its left as the last resort.
    """
    if not summary:
        return base[:cap]
    joined = f"{base}; {summary}" if base else summary
    if len(joined) <= cap:
        return joined
    room = cap - len(summary) - 2
    if room > 1:
        return f"{base[:room - 1]}{_ELLIPSIS}; {summary}"
    return _ELLIPSIS + summary[-(cap - 1):]
```

The caller becomes a single line:

```python
# core/phases/ack.py, replacing :100-102
note = advisories.cap_note("artifacts detected by phase_completion.py", advisory)
```

> [!DECISION D-102] owner=impl-agent date=2026-09-17T00:00:00Z refs=step-5
> impl-plan-review F-2: the sketch's `_records` was undefined. Resolved: the
> `advisory` signal's source is `advisories.read(ticket, phase_id)` (step-3's
> accessor), not a re-probe of `can_complete`. `collect_signals` has exactly one
> non-test call site (`core/phases/ack.py:248`, inside the `--auto` branch,
> strictly after the `:work`→`:ack-needed` transition already ran
> `can_complete(persist=True)` and wrote the artifact for this `phase_id`), so
> reading the persisted envelope is safe and correct. `advisories.read` is added
> to step-5's Interfaces below.

## step-5 — the severity threshold and a threshold-aware gate signal

- Goal: the `advisory` gate signal is clean when no collected record reaches the
  configured threshold, the threshold is an operator-settable knob defaulting to
  `medium`, and `decision` gates still always pause.
- RED: `tests/integration/test_klc117_threshold_settings.py::test_default_threshold_is_medium_and_project_override_wins`,
  `::test_invalid_threshold_value_falls_back_to_default`,
  `tests/integration/test_klc117_gate_threshold.py::test_advisory_signal_clean_below_threshold`,
  `::test_advisory_signal_dirty_when_artifact_missing_or_unreadable`,
  `::test_conditional_gate_auto_proceeds_info_only`,
  `::test_conditional_gate_pauses_on_one_high_record`,
  `::test_decision_gate_still_pauses_with_info_only_records`
  (test-plan rows for AC-9 to AC-12 plus the invalid-threshold and
  decision-gate edge cases) — all seven fail while `_CHECK["advisory"]` is
  `lambda v: not v` over a string.
- GREEN: add `settings.advisory_threshold()`; declare `advisory.threshold` in
  `config/settings.yml` (commented, so resolution still falls through to the
  built-in default) and in `validate_config._SETTINGS_SCHEMA`, whose allow-list
  would otherwise flag it as an unknown key. Change
  `gate_policy.collect_signals` to put a dict under `"advisory"` carrying the
  records and the resolved threshold, and `_CHECK["advisory"]` to a
  threshold-aware predicate that is dirty when the input is absent or
  unreadable. The `decision` branch of `evaluate` is untouched.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_threshold_settings.py tests/integration/test_klc117_gate_threshold.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_gate_policy.py tests/test_settings.py -q`
- Expected: `7 passed` from the first command; `27 passed` from the second (17
  gate-policy plus 10 settings tests, none modified — the other six signals and
  the fail-closed convention are untouched).
- COMMIT: KLC-117 step-5: threshold-aware advisory gate signal with a settings knob
- Affected: `core/skills/settings.py`, `core/skills/validate_config.py`,
  `core/skills/gate_policy.py`, `config/settings.yml`,
  `tests/integration/test_klc117_threshold_settings.py` (new),
  `tests/integration/test_klc117_gate_threshold.py` (new).
- Addresses: AC-9, AC-10, AC-11, AC-12
- Interfaces: `settings.advisory_threshold() -> str` (new);
  `gate_policy.collect_signals` keeps its signature but its `"advisory"` value
  changes from `str` to `dict | None`; `gate_policy.evaluate` unchanged.
- Depends on: step-3
- Code sketch:

```python
# core/skills/settings.py
def advisory_threshold() -> str:
    """Severity at or above which the advisory gate signal is dirty (C-004).

    Rides the existing project-before-framework ladder. An unknown value falls
    back to the built-in default rather than crashing resolution, mirroring how
    every other knob degrades per-knob.
    """
    value = resolve("advisory.threshold", legacy_file="profile.yml",
                    legacy_key="advisory_threshold", default="medium")
    return value if value in ("high", "medium", "low", "info") else "medium"
```

The signal collector and its checker:

```python
# core/skills/gate_policy.py
def _advisory_clean(value) -> bool:
    """Clean only when we have a readable record set and nothing reaches the
    threshold. Absent / unreadable → DIRTY, matching the module's fail-closed
    'absent key = dirty' convention."""
    if not isinstance(value, dict) or "records" not in value:
        return False
    import advisories as _adv
    return not _adv.at_or_above(value["records"], value.get("threshold", "medium"))


_CHECK["advisory"] = _advisory_clean

# inside collect_signals(), replacing `"advisory": advisory or ""` at :225 —
# persist=False is unchanged, so the probe still writes nothing (C-002):
    import settings as _settings
    sig["advisory"] = {"records": _records, "threshold": _settings.advisory_threshold()}
```

And the knob's declaration in the settings front door:

```yaml
# config/settings.yml — shipped COMMENTED, so the built-in default applies
# Ack advisory severity threshold (KLC-117). At or above this severity the
# `advisory` gate signal is dirty and a conditional gate pauses. No legacy file.
# advisory:
#   threshold: medium        # high | medium | low | info. Default: medium.
```

> [!DECISION D-105] owner=impl-agent date=2026-09-17T00:00:00Z refs=step-5
> Discovered during step-5 (not one of the three impl-plan-review findings):
> `tests/integration/test_gate_policy.py`'s `_CLEAN_SIGNALS`/`_CLEAN_SIG` and
> `tests/integration/test_autorunner.py`'s `_CLEAN_SIG` hand-construct the
> `signals` dict fed straight into `gate_policy.evaluate()` using the OLD
> `"advisory": ""` shape. `_advisory_clean` requires a dict with a `records`
> key, so `""` now reads as malformed → dirty, flipping every test that expects
> a clean `evaluate("conditional", ...)` outcome. Neither file is in step-5's
> Affected list, and this is a genuine plan gap (same category as F-1/F-2/F-3,
> found by direct execution rather than the earlier review). FIX: update the
> three fixture constants to `{"records": [], "threshold": "medium"}` — a
> mechanical shape update, not a change to any test's assertions/intent. Both
> files pass unmodified in substance (27 + 28 tests, respectively) after the fix.

## step-6 — status, work and the run orchestrator read the artifact

- Goal: `klc status` and `klc work` print every high and medium record in full
  and a bare count of the rest, and the `/klc:run` skill documents reading
  `ack-advisories.json` instead of an advisory string.
- RED: `tests/integration/test_klc117_status_work_verbs.py::test_status_json_prints_high_medium_in_full_and_counts_remainder`,
  `::test_work_json_prints_high_medium_in_full_and_counts_remainder`,
  `tests/integration/test_klc117_run_orchestrator.py::test_gate_policy_signal_survives_nonempty_summary_string`,
  `tests/integration/test_klc117_run_orchestrator_doc.py::test_run_skill_no_longer_documents_string_based_advisory_reading`
  (test-plan rows for AC-13 and AC-14) — all four fail because neither verb
  emits an advisories key and the skill says nothing about the artifact.
- GREEN: add `advisories.for_display(ticket, phase_id)` returning a dict
  with a `high` list, a `medium` list and an `other_count` integer, or `None`; call it from
  `status.run` (JSON branch and the human render) and `work.next_action`. Both
  verbs read the artifact only — neither calls `can_complete`, which would break
  their read-only contract and spawn git subprocesses on every `klc status`
  (design D-001). Add one paragraph to loop step 6 of
  `klc-plugin/skills/run/SKILL.md` telling the orchestrator to read the artifact
  when `ack --auto` pauses.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_status_work_verbs.py tests/integration/test_klc117_run_orchestrator.py tests/integration/test_klc117_run_orchestrator_doc.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_verbs_json.py tests/integration/test_work_verb.py -q`
- Expected: `4 passed` from the first command; `19 passed` from the second (3
  verbs-json plus 16 work-verb tests, unmodified — the new key is additive, so
  no existing assertion moves).
- COMMIT: KLC-117 step-6: status, work and /klc:run read the advisory artifact
- Affected: `core/skills/advisories.py`, `core/phases/status.py`,
  `core/phases/work.py`, `klc-plugin/skills/run/SKILL.md`,
  `tests/integration/test_klc117_status_work_verbs.py` (new),
  `tests/integration/test_klc117_run_orchestrator.py` (new),
  `tests/integration/test_klc117_run_orchestrator_doc.py` (new).
- Addresses: AC-13, AC-14
- Interfaces: `advisories.for_display(ticket, phase_id) -> dict | None` (new).
  `status.run` and `work.next_action` keep their signatures; `work.next_action`
  gains an optional `advisories` key in its returned dict.
- Depends on: step-5
- Code sketch:

```python
# core/skills/advisories.py
def for_display(ticket: str, phase_id: str):
    """High and medium records in full, everything else as a bare count (AC-13).

    Reads the persisted artifact only — never the gate — so `klc status` and
    `klc work` keep the strictly-read-only contract their docstrings advertise
    (design D-001). None when no artifact exists for this phase.
    """
    envelope = read(ticket, phase_id)
    if not envelope:
        return None
    records = envelope.get("records") or []
    shown = {s: [r for r in records if r.get("severity") == s]
             for s in ("high", "medium")}
    return {"high": shown["high"], "medium": shown["medium"],
            "other_count": len(records) - len(shown["high"]) - len(shown["medium"])}
```

The orchestrator's instruction, appended to loop step 6:

```markdown
<!-- klc-plugin/skills/run/SKILL.md, appended to loop step 6 -->
   - When `ack --auto` pauses on a dirty `advisory` signal, read the phase's
     `<ticket-dir>/<phase-id>/ack-advisories.json` and report its `high` and
     `medium` records to the human, with a bare count of the rest. Never parse
     the summary line or the phase-history note for advisory detail — the JSON
     is the machine-readable source and the note is a pointer to it.
```

> [!DECISION D-101] owner=impl-agent date=2026-09-17T00:00:00Z refs=step-7
> impl-plan-review F-1 (HIGH): the code sketch's bare `_lc.write_meta(ticket, meta)`
> is replaced by the standard meta-mutation envelope every other verb uses —
> `with acquire_lock(ticket): with state_tx.state_tx(ticket, f"migrate-notes
> {ticket}") as tx: ...` — one transaction per ticket, mirroring the bulk-walk
> precedent in `core/phases/heartbeat.py` (`StaleStateError` /
> `NothingToCommitError` swallowed per-ticket so one locked/stale ticket does not
> abort the whole migration walk). Feature-OFF, `state_tx` is a no-op context
> manager (`tx is None`) and the body still runs and writes locally, which is
> required for AC-15/AC-16/AC-16(idempotent) to hold in the single-user tree
> this ticket's own tests run against.

> [!DECISION D-106] owner=impl-agent date=2026-09-17T00:00:00Z refs=step-5
> Found by the first full-suite run (post step-8): `tests/integration/test_orchestrator_run_to_gate.py::test_ack_auto_then_next_after_done`
> hand-constructs a `_CLEAN_SIG` dict (fed straight into `_gp.evaluate` via a
> monkeypatched `collect_signals`) using the OLD `"advisory": ""` shape — same
> D-105 class of gap, in a fourth file not touched by step-5's original sweep.
> FIX: updated `_CLEAN_SIG["advisory"]` to `{"records": [], "threshold": "medium"}`
> (mechanical shape fix, no assertion/intent change); confirmed RED
> (`assert 2 == 0`, `klc ack --auto: paused — advisory not clean`) before the
> fix, `1 passed` after.

## step-7 — the one-time note migration verb

- Goal: `klc migrate-notes` replaces every stored note over the cap with a
  truncated note plus a pointer to its phase artifact, appends exactly one audit
  entry per migrated ticket, covers archived tickets, and is a byte-exact no-op
  on a second run.
- RED: `tests/integration/test_klc117_migration.py::test_migration_truncates_overlong_notes_with_pointer_and_audit_entry`,
  `::test_migration_leaves_short_notes_byte_identical`,
  `::test_migration_idempotent_on_second_run`,
  `::test_migration_covers_archived_tickets_too`
  (test-plan rows for AC-15, AC-16 and the archive edge case) — all four fail
  because the verb does not exist.
- GREEN: add `core/phases/migrate_notes.py` with a `run(argv)` entry point and a
  `--dry-run` flag, plus one dispatch entry in `scripts/klc`'s `LIFECYCLE_CMDS`.
  It walks every ticket directory, including archived ones (an archived ticket
  keeps `phase: archived` in the same `.klc/tickets/<KEY>/` tree — there is no
  separate archive directory, verified 2026-09-17: 88 of the tickets on this
  tree are archived). It rewrites only `note` fields over the cap and touches no
  `phase`, `event`, timestamp or `pick` field (C-005).
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_migration.py -q`
- Expected: `4 passed`.
- COMMIT: KLC-117 step-7: klc migrate-notes, idempotent and archive-aware
- Affected: `core/phases/migrate_notes.py` (new), `scripts/klc`,
  `tests/integration/test_klc117_migration.py` (new).
- Addresses: AC-15, AC-16
- Interfaces: `migrate_notes.migrate_ticket(ticket, dry_run=False) -> dict`
  (new), `migrate_notes.run(argv) -> int` (new).
- Depends on: step-4
- Code sketch:

```python
# core/phases/migrate_notes.py
_POINTER = "see {phase_id}/ack-advisories.json"
_AUDIT_EVENT = "note-migration"


def migrate_ticket(ticket: str, dry_run: bool = False) -> dict:
    """Truncate over-cap notes in one ticket's phase_history. Idempotent.

    Lossy by design (design D-005): the discarded prose is not copied anywhere.
    It stays recoverable from the klc-state branch's git history of meta.json,
    and the audit entry records how much was reclaimed, so the loss is measured.
    A ticket that already carries an audit entry is skipped outright, which is
    what makes a second run byte-identical rather than merely non-crashing.
    """
    meta = _lc.read_meta_ro(ticket)
    history = meta.get("phase_history") or []
    if any(e.get("event") == _AUDIT_EVENT for e in history):
        return {"ticket": ticket, "migrated": 0, "skipped": "already migrated"}
    migrated, reclaimed = 0, 0
    for entry in history:
        note = entry.get("note") or ""
        if len(note) <= _adv.NOTE_CAP:
            continue          # C-005: short notes stay byte-identical
        phase_id = str(entry.get("phase", "")).split(":", 1)[0]
        entry["note"] = _adv.cap_note(note, _POINTER.format(phase_id=phase_id))
        reclaimed += len(note) - len(entry["note"])
        migrated += 1
    if migrated and not dry_run:
        history.append({"phase": meta.get("phase"), "started_at": _lc._now(),
                        "finished_at": _lc._now(), "event": _AUDIT_EVENT,
                        "note": (f"KLC-117: {migrated} over-cap note(s) "
                                 f"truncated, {reclaimed} chars reclaimed")})
        _lc.write_meta(ticket, meta)
    return {"ticket": ticket, "migrated": migrated, "reclaimed": reclaimed}
```

And the dispatch entry that makes it a verb:

```python
# scripts/klc — one entry, alongside the other lifecycle verbs
LIFECYCLE_CMDS = (
    "intake", "status", "next", "ack", "ship", "jump", "abort", "step", "work",
    "retrack", "scope-fix", "task-brief", "build-run", "steal", "remind",
    "heartbeat", "run", "publish", "migrate-notes",
)
```

## step-8 — document what an operator sees at an ack

- Goal: `docs/process.md` describes the advisory record, the artifact, the
  summary line, the threshold knob and the migration verb, so an operator reading
  the process doc is not left with the pre-KLC-117 description of a joined
  string.
- RED: not applicable — this step changes documentation only and adds no
  behaviour; every behavioural claim it records is already pinned by the tests in
  steps 1 to 7.
- GREEN: update the seven-signal table (`docs/process.md:675`) so the `advisory`
  row reads "no record at or above `advisory.threshold`" instead of "empty
  string"; add an "Ack advisories" subsection under `## Human gates` covering the
  record fields, the severity table, the artifact path, the summary format and
  the 200-character note cap; add `migrate-notes` to the `## Verbs` section; note
  in the independent-review section that routed decisions now arrive as `high`
  records. Add the new knob's line to the `config/settings.yml` documentation
  block if step-5 left it out.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc117_run_orchestrator_doc.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -c "import sys; sys.path.insert(0, 'core/skills'); import validate_config; print(validate_config.validate_settings() or 'settings ok')"`
- Expected: `1 passed` from the first command, then `settings ok` — the doc edit
  changes no behaviour, and the settings validator confirms the new dotted key is
  in its allow-list rather than flagged as unknown.
- COMMIT: KLC-117 step-8: document ack advisories, the threshold knob and migrate-notes
- Affected: `docs/process.md`, `config/settings.yml`.
- Addresses: none
- Interfaces: none (documentation only).
- Depends on: step-7

## Test-coverage discipline

Every gate or validator acceptance criterion in this plan maps to a negative test
and a fail-closed test, both written before the step's GREEN:

| behaviour | negative test | fail-closed test |
|---|---|---|
| the producer-contract boundary (AC-1) | `test_bare_string_producer_wrapped_as_legacy_string_info_record` — a bare string is wrapped, not forwarded | `test_record_missing_required_keys_degrades_to_info` — a record with no `message` degrades rather than being dropped |
| severity normalisation (AC-3) | `test_unknown_severity_normalised_to_info_and_flagged` | `test_missing_severity_field_defaults_to_info_and_flagged` |
| the probe's write-free guarantee (AC-5) | `test_probe_persist_false_writes_no_file` — asserts absence, with the write entry points monkeypatched to raise | `test_unwritable_artifact_path_degrades_without_raising` |
| the threshold signal (AC-9) | `test_conditional_gate_pauses_on_one_high_record` | `test_advisory_signal_dirty_when_artifact_missing_or_unreadable` |
| the threshold knob (AC-10) | `test_default_threshold_is_medium_and_project_override_wins` | `test_invalid_threshold_value_falls_back_to_default` |
| the migration (AC-15, AC-16) | `test_migration_leaves_short_notes_byte_identical` | `test_migration_idempotent_on_second_run` — no new audit entry, byte-identical tree |

Every test above drives a public entry point: `advisories.collect` /
`advisories.finish`, `phase_completion.can_complete`,
`gate_policy.collect_signals` and `gate_policy.evaluate`, the real `klc status`
and `klc work` subprocesses, and the `klc migrate-notes` verb. No test asserts on
a private helper.

## Rollback

Steps 1 and 2 are additive and need no rollback. Step 3 is the one irreversible
point in the stack — once the six return sites route through the aggregator, the
success-path message changes shape for every consumer, so reverting it means
reverting steps 4 to 6 as well. Step 7 is the only step that rewrites stored
data; run `klc migrate-notes --dry-run` first, and recover from the `klc-state`
branch's git history of `meta.json` if a run must be undone.
