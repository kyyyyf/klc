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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_repo_root = _file_dir.parent.parent
for _p in (str(_repo_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.shared.paths import klc_ticket_meta_file, project_root  # noqa: E402
import store_lock  # noqa: E402

ARTIFACT_NAME = "advisories.json"            # one phase-keyed file per ticket (KLC-173)
LEGACY_ARTIFACT_NAME = "ack-advisories.json"  # per-phase file of archived tickets, read-only

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
    """The ticket's one advisories.json (phase_id is kept for call-site symmetry)."""
    return klc_ticket_meta_file(ticket).parent / ARTIFACT_NAME


def _legacy_path(ticket: str, phase_id: str) -> Path:
    return klc_ticket_meta_file(ticket).parent / phase_id / LEGACY_ARTIFACT_NAME


def _load_doc(path: Path) -> dict:
    """The phase-keyed document, or {} when absent. Raises OSError when the file
    exists but is unreadable or not an object, so a write never destroys what
    it could not parse (F-007)."""
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                           # noqa: BLE001
        raise OSError(f"{path.name} is unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise OSError(f"{path.name} is not a JSON object")
    return doc


def _corrupt_siblings(path: Path) -> list[Path]:
    return sorted(path.parent.glob("advisories.corrupt-*.json")) if path.parent.is_dir() else []


def store_corrupt(ticket: str) -> bool:
    """True when a corrupt advisories.json was ever moved aside for *ticket*:
    its records are lost, so every phase of the ticket reads dirty. Never raises."""
    try:
        return bool(_corrupt_siblings(artifact_path(ticket, "")))
    except Exception:                                  # noqa: BLE001
        return True


def _move_aside(path: Path) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    os.replace(path, path.with_name(f"advisories.corrupt-{ts}.json"))


def _store(path: Path, phase_id: str, records: list[dict]) -> None:
    """Read-modify-write one phase key under the store lock. No records: drop the
    key, and delete the file once it is empty, so a clean ack leaves no file, no
    key and no directory. A corrupt file is moved aside (never silently replaced)
    to `advisories.corrupt-<ts>.json`; the gate then reads every phase as dirty."""
    with store_lock.locked(path):
        try:
            doc = _load_doc(path)
        except OSError:
            _move_aside(path)
            doc = {}
        if records:
            doc[phase_id] = {"generated_at": datetime.now(timezone.utc)
                                                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "records": records}
        else:
            doc.pop(phase_id, None)
        if not doc:
            if path.exists():
                path.unlink()
            return
        store_lock.atomic_write_text(
            path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


# (ticket, phase) -> True after a persisting finish whose write failed (F-001).
# The ack reads it right after can_complete and stamps the history entry, which
# is what the gate reads; a later successful finish for the pair clears it.
_WRITE_FAILED: dict = {}


def write_failed(ticket: str, phase_id: str) -> bool:
    return bool(_WRITE_FAILED.get((ticket, phase_id)))


def history_marker(ticket: str, phase_id: str):
    """The `extra` fields the ack adds to the `<phase>:ack-needed` history entry
    when this phase's advisories could not be written, else None. A missing key
    is clean only without this marker: a failed write must never read as clean."""
    return {"advisories": "write-failed"} if write_failed(ticket, phase_id) else None


def finish(ticket: str, phase_id: str, sources, persist: bool = True):
    """Collect, persist (ack path only) and render. Returns (records, summary).

    C-002: when `persist` is False NOTHING is written (the probe path used by
    the klc hook's pending line and gate-policy signal collection stays write-free). C-001: an
    unwritable path (OSError) degrades to an extra info record rather than
    raising, so the ack always completes.

    KLC-173: the records live in one `<ticket>/advisories.json` keyed by phase
    id. A clean ack writes nothing; the gate reads the missing key as clean only
    when the ticket history records that phase reaching ack-needed
    (`ack_recorded`). A clean re-ack removes the phase's stale key.
    """
    records = collect(sources)
    path = artifact_path(ticket, phase_id)
    try:
        rel = str(path.relative_to(project_root()))
    except ValueError:
        rel = str(path)
    if persist:
        try:
            _store(path, phase_id, records)
            _WRITE_FAILED.pop((ticket, phase_id), None)
        except OSError as exc:                         # C-001: never block an ack
            _WRITE_FAILED[(ticket, phase_id)] = True
            records.append({"source": "advisories", "severity": "info",
                            "code": "malformed-record",
                            "message": (f"advisory artifact not written — "
                                        f"{type(exc).__name__}"), "ref": rel})
    return records, render_summary(records, rel)


def read(ticket: str, phase_id: str):
    """The phase's persisted envelope, or None when absent/unreadable. Never raises.

    Reads `<ticket>/advisories.json`; when that file has no key for the phase,
    falls back to the legacy per-phase `ack-advisories.json` (archived tickets).
    An unreadable advisories.json is None (the gate stays dirty).
    """
    try:
        path = artifact_path(ticket, phase_id)
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                return None
            env = doc.get(phase_id)
            if isinstance(env, dict):
                return env
            if phase_id in doc:
                return None                            # present but malformed: dirty
        legacy = _legacy_path(ticket, phase_id)
        if legacy.exists():
            return json.loads(legacy.read_text(encoding="utf-8"))
        return None
    except Exception:                                  # noqa: BLE001
        return None


def _ack_entry(ticket: str, phase_id: str):
    """The latest `<phase_id>:ack-needed` history entry, or None. Never raises."""
    try:
        meta = json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))
        target = f"{phase_id}:ack-needed"
        hits = [e for e in meta.get("phase_history") or []
                if isinstance(e, dict) and e.get("phase") == target]
        return hits[-1] if hits else None
    except Exception:                                  # noqa: BLE001
        return None


def ack_recorded(ticket: str, phase_id: str) -> bool:
    """True when meta.json phase_history holds `<phase_id>:ack-needed`. Never raises."""
    return _ack_entry(ticket, phase_id) is not None


def missing_key_is_clean(ticket: str, phase_id: str) -> bool:
    """True when the phase has no record set AND that is a clean outcome: the
    history records the ack, that ack did not record a failed advisories write,
    no corrupt advisories.json was moved aside, and advisories.json is absent or
    a readable object without a malformed entry for the phase (fail-closed).
    Never raises."""
    try:
        entry = _ack_entry(ticket, phase_id)
        if entry is None or entry.get("advisories") == "write-failed":
            return False
        path = artifact_path(ticket, phase_id)
        if _corrupt_siblings(path):
            return False
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or phase_id in doc:
                return False
        return True
    except Exception:                                  # noqa: BLE001
        return False


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
