#!/usr/bin/env python3
"""advisories.py — the one advisory aggregator for the phase-completion gate
(KLC-117).

Owns the record schema, the severity vocabulary, collection from every
producer, the artifact write and the summary line. Producers emit plain dicts
and import nothing from here (design D-002), so a malformed record is a real
runtime case with a real test rather than an impossible type error.

Degrade-not-fail (C-001) is absolute here: nothing in this module raises out
of the advisory path. A producer that raises, a bare string from a
not-yet-converted producer, and a record with a bad or missing severity all
degrade to a visible `info` record rather than crashing collection or being
silently dropped.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_repo_root = _file_dir.parent.parent
for _p in (str(_repo_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.shared.paths import klc_ticket_meta_file, project_root  # noqa: E402

SCHEMA_VERSION = 1
ARTIFACT_NAME = "ack-advisories.json"

SEVERITIES = ("high", "medium", "low", "info")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}
NOTE_CAP = 200          # characters, a data-hygiene invariant, not a knob (Q-004)
_REQUIRED = ("source", "severity", "code", "message", "ref")


def normalise_record(source: str, raw) -> tuple[dict, dict | None]:
    """One well-formed record, plus a companion flag record when `raw` was bad.

    A bare string becomes info/legacy-string (AC-18: no silent forwarding of an
    untyped producer output). A missing or unknown severity becomes info AND
    raises a flag naming the offender, so the mis-declaration is visible (AC-3).
    A dict missing a non-empty `message` degrades to info/malformed-record.
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


def artifact_path(ticket: str, phase_id: str) -> Path:
    return klc_ticket_meta_file(ticket).parent / phase_id / ARTIFACT_NAME


def finish(ticket: str, phase_id: str, sources, persist: bool = True):
    """Collect, persist (ack path only) and render. Returns (records, summary).

    C-002: when `persist` is False NOTHING is written — the probe path used by
    `klc remind` and gate-policy signal collection must stay write-free, so the
    mkdir and the write both sit inside the flag. C-001: an unwritable path
    (OSError on mkdir/write) degrades to an extra info record rather than
    raising — the ack always completes.

    review-fix (HIGH, AC-9): when `persist` is True the envelope is written
    UNCONDITIONALLY, even when `records` is empty — a genuinely clean ack
    (every producer ran and found nothing) writes `records: []`, a real,
    informative envelope. Writing only `if records` made `gate_policy` read
    the absent artifact as DIRTY on the single cleanest possible outcome,
    inverting AC-9's documented behaviour and defeating `klc ack --auto` for
    what is very likely the majority of real acks.
    """
    records = collect(sources)
    path = artifact_path(ticket, phase_id)
    try:
        rel = str(path.relative_to(project_root()))
    except ValueError:
        rel = str(path)
    if persist:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            envelope = {"schema_version": SCHEMA_VERSION, "ticket": ticket,
                        "phase": phase_id,
                        "generated_at": datetime.now(timezone.utc)
                                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "records": records}
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
        return json.loads(artifact_path(ticket, phase_id).read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return None


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
    shown = {s: [r for r in records if r.get("severity") == s] for s in ("high", "medium")}
    return {"high": shown["high"], "medium": shown["medium"],
            "other_count": len(records) - len(shown["high"]) - len(shown["medium"])}
