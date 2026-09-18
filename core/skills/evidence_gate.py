#!/usr/bin/env python3
"""evidence_gate.py — KLC-115: parse and (on the ack path) re-verify the
`## Evidence` section of build-log.md, one entry per acceptance-criterion id.

`parse_evidence` is STRUCTURE ONLY (C-004): it executes nothing, ever. An
entry is anchored by ATTRIBUTION, not by formatting (D-003) — any non-fenced
line naming at least one `AC-<n>` id opens an entry, whether that line is a
`###` heading (KLC-105, KLC-103) or a plain paragraph (KLC-107). This is
verified against the three real Evidence sections this project has written,
not assumed (AC-17): a heading-only rule reads zero entries out of KLC-107.

`check_evidence` (added in step-3) is the re-verifying gate `phase_completion`
calls; this module is split so the parser has no execution dependency at all.
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
_project_root_dir = _file_dir.parent.parent
for _p in (str(_project_root_dir), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import settings  # noqa: E402
import spec_saoc as _saoc  # noqa: E402
import verify_runner  # noqa: E402

# --- the anchor grammar (D-003, D-004) ---------------------------------------

_AC_ID = re.compile(r"\bAC-(\d+)\b")
_RANGE = re.compile(r"\bAC-(\d+)\s*\.\.\s*AC-(\d+)\b")
_FENCE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_CMD = re.compile(r"^\s*\$\s+(\S.*)$")
_VERDICT = re.compile(r"(?im)^\s*verdict:\s*(pass|deferred)\s*(?:\((.*)\))?\s*$")

PASS, DEFERRED, MALFORMED = "pass", "deferred", "malformed"

# A paragraph anchor (no heading markup) is given a level higher than any real
# heading can reach, so ANY subsequent heading — of any level — ends its span;
# a real Evidence section never nests a heading deeper than level 6.
_PARAGRAPH_LEVEL = 99


@dataclass
class Entry:
    ac_ids: list[str]
    commands: list[str]
    output: str
    verdict: str            # PASS | DEFERRED | MALFORMED
    reason: str = ""         # non-empty when verdict is DEFERRED
    anchor_line: int = 0


def _anchor_ids(line: str) -> list[str]:
    """Ids named by a non-fenced line. Ranges expand first (D-004), then plain
    `AC-<n>` mentions in what remains; order preserved, duplicates dropped."""
    ids = [f"AC-{n}" for lo, hi in _RANGE.findall(line)
           for n in range(int(lo), int(hi) + 1)]
    ids += [f"AC-{n}" for n in _AC_ID.findall(_RANGE.sub("", line))]
    return list(dict.fromkeys(ids))


def evidence_section(text: str) -> str | None:
    """The body under the level-2 `## Evidence` heading, up to the next
    level-2 heading or the end of the document. `None` when no such heading
    exists at all."""
    m = re.search(r"^## Evidence\b", text or "", re.MULTILINE)
    if not m:
        return None
    after = text[m.end():]
    nxt = re.search(r"^## ", after, re.MULTILINE)
    return after[:nxt.start()] if nxt else after


def _extract_fenced(body_lines: list[str]) -> tuple[list[str], list[str]]:
    """(commands, output_lines) from the fenced blocks inside *body_lines*,
    tracking fence state locally so a verdict line elsewhere in the body is
    never mistaken for fenced content."""
    commands: list[str] = []
    output: list[str] = []
    in_fence = False
    for line in body_lines:
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        cm = _CMD.match(line)
        if cm:
            commands.append(cm.group(1).strip())
        elif line.strip():
            output.append(line)
    return commands, output


def _extract_verdict(body_lines: list[str]) -> tuple[str | None, str]:
    """The first `verdict:` line found OUTSIDE any fence in *body_lines*."""
    in_fence = False
    for line in body_lines:
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _VERDICT.match(line)
        if m:
            return m.group(1).lower(), (m.group(2) or "").strip()
    return None, ""


def parse_evidence(text: str, ac_ids) -> tuple[dict[str, Entry], list[Entry]]:
    """STRUCTURE ONLY — executes nothing (C-004). Returns `(by_ac_id, malformed)`.

    An entry runs from its anchor line to the next anchor or the next heading
    at the same-or-higher level (a paragraph anchor is ended by ANY heading —
    it has no level of its own to be "higher" than). An entry is well-formed
    only with at least one command line (a fenced `$ ...` line) AND at least
    one non-command line inside its fences (the captured output); a
    not-well-formed entry is MALFORMED and never covers the AC it would have.
    A `verdict: deferred` with an empty reason is likewise MALFORMED (AC-3).
    Ids outside *ac_ids* are ignored rather than fabricated into coverage
    (the AC inventory has exactly one parser, C-008).
    """
    known = set(ac_ids or [])
    lines = (text or "").splitlines()
    in_fence = False
    anchors: list[dict] = []
    cur: dict | None = None
    # review-fix (HIGH, AC-1/AC-17/AC-19): a non-heading line may open a NEW
    # anchor only when it is paragraph-INITIAL — preceded by a blank line, a
    # heading, or the section start — never mid-paragraph. Without this, a
    # grammatical continuation line that happens to mention a DIFFERENT AC id
    # (e.g. a multi-line parenthetical) forks a competing anchor that steals
    # the next fenced command+output block from the paragraph it actually
    # belongs to, misattributing it to unrelated ACs (verified against the
    # real KLC-107 build-log.md).
    at_paragraph_start = True

    for i, line in enumerate(lines):
        is_fence_line = bool(_FENCE.match(line))
        if is_fence_line:
            in_fence = not in_fence
            if cur is not None:
                cur["body"].append(line)
            at_paragraph_start = True
            continue
        if in_fence:
            if cur is not None:
                cur["body"].append(line)
            continue
        hm = _HEADING.match(line)
        was_paragraph_start, at_paragraph_start = at_paragraph_start, bool(hm)
        if not line.strip():
            at_paragraph_start = True
            continue
        ids = _anchor_ids(line) if (hm or was_paragraph_start) else []
        if ids:
            level = len(hm.group(1)) if hm else _PARAGRAPH_LEVEL
            cur = {"ids": ids, "level": level, "anchor_line": i + 1, "body": []}
            anchors.append(cur)
            continue
        if hm and cur is not None and len(hm.group(1)) <= cur["level"]:
            cur = None
            continue
        if cur is not None:
            cur["body"].append(line)

    by_ac: dict[str, Entry] = {}
    malformed: list[Entry] = []
    for a in anchors:
        commands, output_lines = _extract_fenced(a["body"])
        verdict_kw, reason = _extract_verdict(a["body"])
        well_formed = bool(commands) and bool(output_lines)
        if not well_formed:
            verdict = MALFORMED
        elif verdict_kw in (None, PASS):
            verdict, reason = PASS, ""
        elif verdict_kw == DEFERRED:
            verdict = DEFERRED if reason else MALFORMED
        else:
            verdict = MALFORMED  # an unrecognised verdict keyword never counts as covered

        entry = Entry(ac_ids=[i for i in a["ids"] if i in known],
                      commands=commands, output="\n".join(output_lines),
                      verdict=verdict, reason=reason, anchor_line=a["anchor_line"])
        if verdict == MALFORMED:
            malformed.append(entry)
            continue
        for ac in entry.ac_ids:
            by_ac[ac] = entry
    return by_ac, malformed


# --- step-3: the re-verifying gate -------------------------------------------

BLOCK, SURFACE = "block", "surface"

# D-204: an inability to observe is never a blocking reason token; only these
# two mean "a definite negative observation".
_NO_ENTRY = "no-entry"
_RERUN_FAILED = "rerun-failed"


@dataclass
class Finding:
    ac_id: str
    code: str
    severity: str       # BLOCK or SURFACE
    message: str


@dataclass
class Report:
    track: str
    findings: list[Finding] = field(default_factory=list)
    block_reason: str | None = None

    @property
    def surfaced(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SURFACE]


def _mode(track: str) -> str:
    """Track = floor (C-002), mirroring `ac_test_coverage._active`: XS off,
    S surface-only, M/L/unknown block."""
    t = (track or "").strip().upper()
    if t == "XS":
        return "skip"
    if t == "S":
        return "surface"
    return "block"


def _read(ticket: str, name: str) -> str:
    try:
        from core.shared.paths import klc_ticket_meta_file
        return (klc_ticket_meta_file(ticket).parent / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_meta_ro(ticket: str) -> dict:
    try:
        import lifecycle as _lc
        return _lc.read_meta_ro(ticket) or {}
    except Exception:                                  # noqa: BLE001
        return {}


def _repo_root(repo=None) -> Path:
    if repo is not None:
        return Path(repo)
    try:
        from core.shared.paths import project_root
        return project_root()
    except Exception:                                  # noqa: BLE001
        return _project_root_dir


def _waived(ticket: str):
    """D-005: `meta.deferred_verify_evidence` — `True` waives the whole arm,
    a list waives only the named AC ids, absence waives nothing."""
    val = _read_meta_ro(ticket).get("deferred_verify_evidence")
    if val is True:
        return True
    if isinstance(val, list):
        return set(val)
    return set()


def _is_waived(waived, ac_id: str) -> bool:
    return waived is True or ac_id in waived


def _block_or_surface(report: Report, mode: str, ac_id: str, code: str,
                      waived, message: str) -> None:
    """A definite negative observation (AC-4/AC-6/AC-18): blocks on M/L unless
    the id is waived, surfaces on S, is unreachable on XS (mode already
    filtered to 'skip' before this is ever called)."""
    if mode == "block" and not _is_waived(waived, ac_id):
        report.findings.append(Finding(ac_id, code, BLOCK, message))
        report.block_reason = (message if report.block_reason is None
                               else report.block_reason + "; " + message)
    else:
        note = message
        if mode == "block":  # waived on M/L — say so, so the waiver is auditable
            note = message + " — waived via meta.deferred_verify_evidence"
        report.findings.append(Finding(ac_id, code, SURFACE, note))


def _surface(report: Report, ac_id: str, code: str, message: str) -> None:
    """D-204: an inability to observe ALWAYS surfaces, on every track — never
    a block, regardless of mode/waiver."""
    report.findings.append(Finding(ac_id, code, SURFACE, message))


def check_evidence(ticket: str, track: str, repo=None, *, run_commands: bool,
                   deadline: float | None = None) -> Report:
    """Block a build whose Evidence section leaves an acceptance criterion
    without a well-formed entry (AC-4/AC-18) or whose pass-claiming entry
    exits non-zero on re-run (AC-6); surface every outcome the gate could not
    observe (AC-7, D-204); execute nothing at all when *run_commands* is False
    (AC-5, C-004 — the read-only probe path).

    *deadline* (review-fix, HIGH): a `time.monotonic()` value shared across
    the WHOLE verification arm for one ack (this module, `step_verify`,
    `ac_test_coverage`) — passed down from `can_complete_build` so the total
    ack ceiling is one `verify.arm_budget_seconds`, not one per arm. `None`
    (the default, e.g. a standalone/test call) computes a fresh one.
    """
    mode = _mode(track)
    report = Report(track=track)
    if mode == "skip":
        return report
    try:
        ac_ids = [ac.id for ac in _saoc.parse_acs(_read(ticket, "spec.md"))]
    except Exception:                                  # noqa: BLE001
        ac_ids = []
    if not ac_ids:
        return report

    body = evidence_section(_read(ticket, "build-log.md")) or ""
    by_ac, _malformed = parse_evidence(body, ac_ids)
    waived = _waived(ticket)

    for ac in ac_ids:
        if ac not in by_ac:
            _block_or_surface(report, mode, ac, _NO_ENTRY, waived,
                              f"{ac}: no well-formed Evidence entry")

    if not run_commands:
        return report

    budget = settings.verify_entry_budget()
    root = _repo_root(repo)
    if deadline is None:
        deadline = time.monotonic() + settings.verify_arm_budget()
    done: set[int] = set()
    for entry in by_ac.values():
        if id(entry) in done:
            continue
        done.add(id(entry))
        if entry.verdict != PASS:      # AC-3: a well-formed deferral is not re-run
            continue
        for command in entry.commands:
            if time.monotonic() >= deadline:
                for ac in entry.ac_ids:
                    _surface(report, ac, "unverified-arm-budget-exhausted",
                             f"{ac}: unverified: arm-budget-exhausted — the arm "
                             f"budget was spent before this entry ran")
                break
            v = verify_runner.run(command, budget_s=budget, cwd=str(root))
            if v.state == verify_runner.FAILED:          # AC-6 — the only re-run BLOCK
                for ac in entry.ac_ids:
                    _block_or_surface(
                        report, mode, ac, _RERUN_FAILED, waived,
                        f"{ac}: Evidence entry claims pass but the re-executed "
                        f"command exited non-zero ({command!r}, exit {v.exit_code})")
            elif v.state == verify_runner.UNVERIFIED:     # AC-7 + D-204 — ALWAYS surface
                for ac in entry.ac_ids:
                    _surface(report, ac, f"unverified-{v.reason}",
                            f"{ac}: unverified: {v.reason} ({v.detail})")
    return report


_SEVERITY = {_NO_ENTRY: "medium", _RERUN_FAILED: "medium"}


def warn_lines(report: Report) -> list[str]:
    """Compact one-line-per-finding SURFACE advisories, for this module's own
    tests/CLI (mirrors `ac_test_coverage.warn_lines`)."""
    return [f"evidence[{f.code}]: {f.message}" for f in report.surfaced]


def advisory_records(report: Report) -> list[dict]:
    """The KLC-117 record form of `warn_lines` — `source="verify"` so this
    arm's findings share the aggregator's one advisory stream with every
    other verification site (the design predates KLC-117; adapted here)."""
    return [{"source": "verify", "severity": _SEVERITY.get(f.code, "info"),
            "code": f"verify.{f.code}", "message": f.message, "ref": f.ac_id}
            for f in report.surfaced]
