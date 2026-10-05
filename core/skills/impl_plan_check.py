"""impl_plan_check.py — shared impl-plan parser and violation detector.

Single source of truth for step-field enforcement; imported by both
tests/prompt_harness.py (offline harness) and core/skills/phase_completion.py
(gate at discovery-lite S and design M/L ack).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow standalone import and use from tests/ (project root not always in path)
_SKILLS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SKILLS_DIR.parent.parent
for _p in (str(_PROJECT_ROOT), str(_SKILLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spec_selfreview import PLACEHOLDER_TOKENS  # noqa: E402

REQUIRED_STEP_FIELDS = (
    "Goal", "VERIFY", "COMMIT", "Affected", "Interfaces", "Expected", "Code sketch"
)

# RED-marker parser kept in lock-step with phase_completion.py:413 (commit
# 9069f1f), STRUCTURE and all: match the FIRST `RED:` line only and test its
# captured remainder for "not applicable" — never a whole-body `.*` scan (which
# would let an unrelated prose line reading "…red: … not applicable" wrongly
# exempt a genuine-RED step). `\**` tolerates markdown emphasis between `RED` and
# the colon, so `RED:`, `**RED:**` and `**RED**:` all parse identically.
_RED_LINE_RE = re.compile(r"(?i)\bRED\**:(.+)")


def _red_not_applicable(body: str) -> bool:
    """True iff the FIRST `RED:` line marks the step as not applicable."""
    m = _RED_LINE_RE.search(body)
    return bool(m and "not applicable" in m.group(1).lower())
_CODE_FENCE_RE = re.compile(r"```[a-z]*\n([\s\S]+?)```")
# KLC-114 review round 1 (MEDIUM, AC-13): both the opening AND closing ```
# must sit at the START of a line (optional leading indentation) — the old
# pattern had no line-anchor, so a literal ``` occurring MID-LINE inside a
# one-line field value (e.g. `VERIFY: `sh -c "echo '```' && echo 2
# passed"`) paired up with the step's OWN real code-sketch fence further
# down the body, and `.sub("", body)` erased every field in between
# (Expected, Affected, Interfaces, Rollback, Depends on, COMMIT — all
# silently emptied). A markdown fence is a LINE-level construct; this
# regex now only ever matches a genuine one.
_ANY_FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n[\s\S]*?^[ \t]*```[ \t]*$", re.MULTILINE)


def _has_code_sketch(body: str) -> bool:
    """True when body contains a non-empty fenced block."""
    m = _CODE_FENCE_RE.search(body)
    return m is not None and bool(m.group(1).strip())


# Optional `Addresses: AC-n[, AC-m]` line — declares which ACs a step closes
# (KLC-097 bridge). OPTIONAL and tolerant: absent means "not declared", never an
# error, and it is NOT a REQUIRED_STEP_FIELD, so no existing impl-plan is invalidated.
_ADDRESSES_RE = re.compile(r"(?im)^\s*[-*]?\s*\*{0,2}Addresses\*{0,2}:\s*(.+)$")


def _parse_addresses(body: str) -> list[str]:
    """Extract AC-ids from a step's optional `Addresses:` line; [] when absent.

    Fences are stripped FIRST (same reason `impl_plan_violations` does it): an
    `Addresses: AC-…` line inside a code sketch / config snippet is example content,
    not step metadata, and must not fabricate an AC→step link (review MEDIUM/P2).
    Duplicate AC-ids are de-duplicated order-preservingly — the mapping is a set of
    ACs per step (review LOW). Reuses testplan_review._AC_ID_RE (the single AC-id
    class), imported lazily to avoid any module-load import cycle."""
    m = _ADDRESSES_RE.search(_ANY_FENCE_RE.sub("", body))
    if not m:
        return []
    import testplan_review as _tpr  # noqa: E402 — lazy: single-source AC-id regex
    return list(dict.fromkeys(_tpr._AC_ID_RE.findall(m.group(1))))


def step_ac_map(text: str) -> dict[str, list[str]]:
    """TOTAL map of every step-id → its addressed AC-ids ([] when the step declares
    none — KLC-097). A total map hands a consumer (the future drift-check AC↔code
    arrow) a complete step inventory so undeclared steps are visible, not lost."""
    return {s["id"]: s["addresses"] for s in parse_impl_plan_steps(text)}


def parse_impl_plan_steps(text: str) -> list[dict]:
    """Split impl-plan markdown into steps keyed by '## step-N — title'.

    Each step dict carries `id`, `title`, `body`, and `addresses` (the AC-ids from
    an optional `Addresses:` line, [] when the step declares none — KLC-097)."""
    pattern = re.compile(r"(?m)^##\s+(step-\d+)\s*[—-]\s*(.+)$")
    matches = list(pattern.finditer(text))
    steps = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        steps.append({
            "id": m.group(1),
            "title": m.group(2).strip(),
            "body": body,
            "addresses": _parse_addresses(body),
        })
    return steps


# --- single step-field extractor (KLC-113, AC-11/AC-12/AC-13) ----------------
#
# Promoted out of task_brief.py's tolerant Interfaces/COMMIT regexes (D-003)
# and replaces core/skills/artefacts.py's separate `_extract_impl_step`
# (which only matched one legacy bolded-plus-noun field spelling — dead
# against every real plan, which writes `- Affected:` / `- RED:`). ONE
# extractor, tolerant of both `- Field:` and `**Field**:`.

_STEP_FIELD_NAMES = ("Goal", "RED", "GREEN", "VERIFY", "COMMIT", "Affected",
                     "Interfaces", "Expected", "Rollback", "Depends on")

# Two real historical field names need a generalised (not hardcoded-literal)
# tolerance: 27 archived tickets (e.g. .klc/tickets/KLC-001/impl-plan.md)
# spell "Affected" and "Expected" with a trailing noun ("files"/"tests"),
# inline-value. Matching them via an optional-trailing-word fragment — never
# a hardcoded legacy field-name literal — keeps AC-11's grep-for-legacy-regex
# check clean while still parsing those plans with the SAME extractor.
_OPTIONAL_WORD = {"Affected": r"(?:\s+[a-z]+)?", "Expected": r"(?:\s+[a-z]+)?"}


def _step_field_fragment(name: str) -> str:
    if name == "Depends on":
        return r"Depends[ -]on"  # both spellings seen in real plans
    return re.escape(name) + _OPTIONAL_WORD.get(name, "")


_STEP_BOUNDARY_FRAGMENTS = [_step_field_fragment(n) for n in _STEP_FIELD_NAMES] + [
    r"Code sketch", r"Addresses",
]
_STEP_NEXT = "|".join(_STEP_BOUNDARY_FRAGMENTS)


# KLC-114 F-1: a trailing annotation parenthetical (`(new)`, `(modified)`, …)
# is a NOTE about the path, not part of it. Revision-1 of the step-ledger scope
# rule stripped it only OUTSIDE the backtick-captured group, so every `(new)`
# written INSIDE backticks (the common real spelling, `` `core/skills/x.py
# (new)` ``) survived into the allow-list and read as scope drift.
_ANNOTATION_RE = re.compile(
    r"\s*\((?:new|deleted|removed|regenerated|modified|renamed)[^)]*\)\s*$", re.I)


def _strip_annotation(entry: str) -> str:
    """Strip a trailing annotation parenthetical and surrounding punctuation
    from one `Affected:` entry, whether it arrived backtick-wrapped or not."""
    return _ANNOTATION_RE.sub("", entry.strip().strip("`").strip()).strip().rstrip(",.").strip()


def _split_paths(value: str) -> list[str]:
    """Split an `Affected:` field value into individual paths. Tolerates a
    backtick-wrapped list (`` `a.py`, `b.py` (new) ``, any punctuation
    between entries) and a plain comma-separated list with a trailing
    period (the real spelling `core/skills/x.py, tests/test_x.py.`). An
    annotation parenthetical is stripped identically whether it sits inside
    or outside the backtick-captured group (KLC-114 F-1)."""
    if not value:
        return []
    backticked = re.findall(r"`([^`]+)`", value)
    if backticked:
        return [p for p in (_strip_annotation(b) for b in backticked) if p]
    paths = []
    for part in value.rstrip(".").split(","):
        part = _strip_annotation(part)
        if part:
            paths.append(part)
    return paths


def extract_step_fields(body: str) -> dict:
    """Read one step body into its declared fields, tolerating both the
    ``- Field:`` and ``**Field**:`` spellings real plans use (and the two
    legacy inline-value field names above). Fences are stripped first so a
    code sketch cannot masquerade as step metadata.

    Returns a dict with keys `goal`, `red`, `green`, `verify`, `commit`,
    `affected` (list[str]), `interfaces`, `expected`, `rollback`,
    `depends_on` — `""` (or `[]` for `affected`) when a field is absent.
    """
    clean = _ANY_FENCE_RE.sub("", body)
    out: dict[str, object] = {}
    for name in _STEP_FIELD_NAMES:
        frag = _step_field_fragment(name)
        rx = re.compile(
            rf"(?ims)^[ \t]*[-*]?[ \t]*\*{{0,2}}{frag}\*{{0,2}}:\*{{0,2}}[ \t]*"
            rf"(.+?)(?=\n[ \t]*[-*]?[ \t]*\*{{0,2}}(?:{_STEP_NEXT})\*{{0,2}}:|\Z)"
        )
        m = rx.search(clean)
        key = name.lower().replace(" ", "_")
        out[key] = m.group(1).strip() if m else ""
    out["affected"] = _split_paths(out["affected"])
    return out


def impl_plan_violations(text: str) -> list[str]:
    """Return human-readable violations found in an impl-plan."""
    steps = parse_impl_plan_steps(text)
    if not steps:
        return ["no steps found in impl-plan"]

    violations: list[str] = []
    for step in steps:
        body = step["body"]
        sid = step["id"]

        # Strip fenced blocks before field and placeholder detection so that
        # content inside code sketches (e.g. # Code sketch: or TODO) does not
        # falsely satisfy or trigger checks.
        body_outside_fences = _ANY_FENCE_RE.sub("", body)
        _not_applicable = _red_not_applicable(body_outside_fences)
        for field in REQUIRED_STEP_FIELDS:
            if field == "Code sketch" and _not_applicable:
                continue
            pattern = re.compile(
                rf"(?im)(?:\*\*{re.escape(field)}\b|\b{re.escape(field)}:)"
            )
            if not pattern.search(body_outside_fences):
                violations.append(f"{sid}: missing required field '{field}'")
        for token in PLACEHOLDER_TOKENS:
            if token == "...":
                if re.search(r"(?<![\w.])\.\.\.(?![\w.])", body_outside_fences):
                    violations.append(f"{sid}: contains placeholder token '...'")
            else:
                if token in body_outside_fences:
                    violations.append(f"{sid}: contains placeholder token '{token}'")

        if re.search(r"```[a-z]*\s*```", body):
            violations.append(f"{sid}: contains empty code fence")

        if not _not_applicable:
            if not _has_code_sketch(body):
                violations.append(
                    f"{sid}: missing code sketch (add a non-empty fenced block, "
                    "or mark 'RED: not applicable' for prompt/doc/config steps)"
                )

    return violations
