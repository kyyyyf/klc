#!/usr/bin/env python3
"""spec_selfcheck.py — deterministic spec self-check gate (KLC-083).

Given a `spec.md`, run the checks that CAN be anchored mechanically and surface
the rest as questions/checklists for the human and for the independent spec
reviewer (KLC-084). Modelled on `phase_completion.py`: a phase-gating predicate
that reads an artifact and returns a verdict, but richer — it distinguishes
BLOCK findings (objective, must-not-silently-pass) from SURFACE findings
(heuristics and judgment cues the author / KLC-084 act on).

The 083 ↔ 084 split (see design/options.md):
  * DETERMINISTIC here (reliable, mechanical) — SAOC format, open
    [NEEDS CLARIFICATION] markers.
  * HEURISTIC here (best-effort, SURFACED, may false-positive) — AC testability,
    WHAT-not-HOW leakage, internal contradiction, self-completeness.
  * JUDGMENT — deferred to KLC-084 — true constitution conformance, deep
    semantic contradiction, real intent-completeness. This gate only SURFACES
    the constitution REVIEW-principle checklist (via the KLC-082 reader); it
    never LLM-adjudicates conformance. The one DETERMINISTIC constitution
    principle (klc-state-not-tracked-on-main) is a code-branch gate, not
    spec-relevant, so it is intentionally NOT run here.

Reuse (single source of truth):
  * `spec_saoc` — the SAOC recogniser/validator (format + testability heuristic).
  * `constitution` — the KLC-082 reader; the ONLY loader of the constitution.
    Never re-parses config/constitution.yml.

Degrade-not-fail (itself a constitution principle): if the constitution reader
or file is absent/malformed, the constitution dimension yields a single degraded
SURFACE note and every other dimension still runs. The gate never crashes a phase.

Track scaling: XS runs the LIGHT set (format + markers + constitution surfacing).
S/M/L run the FULL set (adds testability, WHAT-not-HOW, contradiction,
completeness, and coverage). XS pays only the cheap format/marker cost. The
coverage dimension (KLC-089) scales further inside itself: Missing-only on S,
Missing plus Partial on M/L.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Package-safe path setup (mirrors constitution.py / phase_completion.py): make
# both the project root and this skills dir importable so the bare `import
# spec_saoc` / `import constitution` resolve under script AND package invocation.
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
for _p in (str(_project_root), str(_file_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import spec_saoc as _saoc  # noqa: E402

# Severities.
BLOCK = "block"
SURFACE = "surface"

# Track sets. LIGHT is the XS floor; FULL adds the heavier consistency checks.
_LIGHT = {"format", "markers", "constitution"}
_HEAVY = {"testability", "what-not-how", "contradiction", "completeness", "coverage"}

# The [NEEDS CLARIFICATION] marker (spec-kit convention). Any occurrence that
# survives in the spec is an UNRESOLVED question by definition — the author
# resolves one by answering it inline and deleting the marker.
_MARKER_RE = re.compile(r"\[NEEDS CLARIFICATION\b[^\]]*\]", re.IGNORECASE)

# Fence / inline-code stripping so a marker or cue *shown as an example* inside
# code does not trip the check. All four Markdown code forms are removed:
# ```-fences, ~~~-fences, 4-space/tab indented blocks, and `inline` spans.
_FENCED_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_TILDE_FENCE_RE = re.compile(r"~~~[\s\S]*?~~~", re.MULTILINE)
_INDENTED_RE = re.compile(r"(?m)^(?: {4,}|\t).*$")
_INLINE_RE = re.compile(r"`[^`\n]*`")

# The requirement/AC sections a BLOCKING marker can live in. Scoping the marker
# scan here (rather than the whole doc) means a spec that merely DOCUMENTS the
# marker convention in its narrative (Goals / Non-goals / Problem) is not
# self-blocked — only an unknown attached to an actual requirement blocks.
_REQUIREMENT_HEADINGS = (
    ("acceptance",),
    ("requirement",),
    ("open question", "open questions"),
    ("constraint",),
)

# Vague-adjective blocklist (KLC-089 / E-05, borrowed from spec-kit's /analyze).
# An acceptance criterion that PROMISES a quality — the system will be `fast`,
# `secure`, … — without a measurable criterion is asserting a quality rather than
# specifying one. Matching is WHOLE-WORD (leading + trailing `\b`) so `secure`
# does not fire inside `security` and `fast` does not fire inside `steadfast`
# (C-004). This is a deliberate, distinct addition to spec_saoc's condition-only
# `_VAGUE_TOKENS` check — both may flag `intuitive`, and that overlap is intended.
_VAGUE_ADJECTIVES = ("fast", "scalable", "secure", "intuitive", "robust",
                     "performant", "reliable")
_VAGUE_ADJ_RE = re.compile(r"\b(" + "|".join(_VAGUE_ADJECTIVES) + r")\b", re.IGNORECASE)
# A digit anywhere in the AC body is a cheap "quantified" signal — a measurable
# criterion is present, so the asserted quality is treated as specified and left
# quiet (e.g. `fast (p95 < 200ms)`).
_MEASURABLE_RE = re.compile(r"\d")

# WHAT-not-HOW cues: implementation detail smuggled into a requirement section.
_HOW_CUES = (
    re.compile(r"\b[\w/-]+\.(?:py|js|ts|tsx|go|rs|java|rb|yml|yaml|json|sql|sh|c|cpp|h)\b"),
    re.compile(r"(?i)\b(?:using|via|implement(?:ed|ing)?\s+with|by\s+calling)\s+(?:the\s+)?[\w.]+"),
    re.compile(r"(?i)\b(?:for\s+loop|while\s+loop|hash\s?map|mutex|subprocess|regex|SQL\s+query|thread\s+pool)\b"),
)

# Antonym action pairs for the crude contradiction heuristic. Each tuple is one
# semantic axis; two ACs whose actions land on opposite sides AND that share a
# significant object word are flagged as a POSSIBLE contradiction (surfaced).
_ANTONYMS = (
    ({"reject", "rejects", "block", "blocks", "deny", "denies", "refuse", "refuses", "disallow", "disallows"},
     {"accept", "accepts", "allow", "allows", "permit", "permits", "pass", "passes"}),
    ({"enable", "enables"}, {"disable", "disables"}),
    ({"include", "includes"}, {"exclude", "excludes"}),
    ({"add", "adds"}, {"remove", "removes", "delete", "deletes"}),
    ({"require", "requires"}, {"forbid", "forbids", "prohibit", "prohibits"}),
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "with", "when", "then",
    "given", "if", "is", "are", "be", "it", "its", "that", "this", "on", "in",
    "at", "by", "from", "as", "into", "not", "no", "any", "all", "each", "must",
    "should", "will", "shall", "spec", "specification", "value", "values",
}


@dataclass
class Finding:
    dimension: str
    severity: str
    message: str
    ref: str = ""  # e.g. an AC id


@dataclass
class Report:
    track: str
    findings: list[Finding] = field(default_factory=list)
    constitution_checklist: list[dict] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == BLOCK]

    @property
    def surfaced(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SURFACE]

    @property
    def ok(self) -> bool:
        """No BLOCK findings — surfaced items do not fail the gate."""
        return not self.blocking


# --- helpers ----------------------------------------------------------------

def _strip_code(text: str) -> str:
    t = _FENCED_RE.sub("", text)
    t = _TILDE_FENCE_RE.sub("", t)
    t = _INDENTED_RE.sub("", t)
    t = _INLINE_RE.sub("", t)
    return t


def _requirement_regions(text: str) -> str:
    """Concatenated bodies of the requirement/AC sections a marker can block in.

    Falls back to the whole document when none of those sections is present, so a
    minimal spec is still scanned rather than silently skipped.
    """
    regions = [b for words in _REQUIREMENT_HEADINGS if (b := _section_body(text, words))]
    return "\n".join(regions) if regions else text


def _section_body(text: str, heading_words: tuple[str, ...]) -> str:
    """Return the body under the first `## <heading>` matching *heading_words*,
    up to the next level-2 heading. Empty string if the heading is absent."""
    lines = text.splitlines()
    body: list[str] = []
    capturing = False
    for line in lines:
        if re.match(r"^##\s+", line):
            if capturing:
                break
            head = line.lstrip("#").strip().lower()
            capturing = any(head.startswith(w) for w in heading_words)
            continue
        if capturing:
            body.append(line)
    return "\n".join(body)


def _keywords(s: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z_-]{3,}", s.lower())
    return {w for w in words if w not in _STOPWORDS}


# --- the [NEEDS CLARIFICATION] marker check (public; used by phase_completion) ---

def unresolved_markers(text: str) -> list[str]:
    """Return every open [NEEDS CLARIFICATION …] marker attached to a requirement.

    These are the questions the human/KLC-084 must resolve; an unresolved marker
    must not silently pass. Deterministic. The scan is scoped to the requirement/
    AC sections and strips all code forms, so a spec that merely NAMES the marker
    in prose or an example does not self-block (a meta-spec problem otherwise).
    """
    # Strip code FIRST, then derive sections from the stripped text. Order
    # matters: a `## …` line inside a fenced example must NOT define a section
    # boundary, or a later REAL marker in the actual requirement section would be
    # omitted — a BLOCKING gate that silently MISSES is worse than an over-block.
    region = _requirement_regions(_strip_code(text))
    return [m.group(0) for m in _MARKER_RE.finditer(region)]


# --- individual dimensions --------------------------------------------------

def _check_format(text: str) -> list[Finding]:
    """Format dimension (LIGHT, all tracks).

    A duplicate AC id is an OBJECTIVE, deterministic authoring defect → BLOCK.
    A non-SAOC AC is SURFACEd (advisory), not hard-failed: legacy specs predate
    the format, so blocking it would break them — rigor scales, the convention
    rolls out via the agents plus this surfaced warning.
    """
    out: list[Finding] = []
    acs = _saoc.parse_acs(text)
    if not acs:
        out.append(Finding("format", SURFACE, "no acceptance criteria found (expected AC-<n> lines)"))
        return out

    # Duplicate AC ids → BLOCK, in the LIGHT set so even XS catches them.
    seen: dict[str, int] = {}
    for ac in acs:
        seen[ac.id] = seen.get(ac.id, 0) + 1
    for ac_id, n in seen.items():
        if n > 1:
            out.append(Finding("format", BLOCK, f"duplicate acceptance-criterion id {ac_id} ({n}×)", ref=ac_id))

    # Non-SAOC ACs → SURFACE.
    for ac in acs:
        if not ac.is_wellformed:
            missing = ", ".join(ac.missing_parts())
            out.append(Finding(
                "format", SURFACE,
                f"{ac.id} is not in SAOC form (Subject · Action · Object · Condition); "
                f"missing/invalid: {missing}",
                ref=ac.id,
            ))
    return out


def _check_markers(text: str) -> list[Finding]:
    return [
        Finding("markers", BLOCK, f"unresolved clarification: {mk} — resolve before build", ref=mk)
        for mk in unresolved_markers(text)
    ]


def _check_testability(text: str) -> list[Finding]:
    out: list[Finding] = []
    for ac in _saoc.parse_acs(text):
        if not ac.is_wellformed:
            continue  # format check already owns malformed ACs
        weak = _saoc.weak_condition(ac.condition)
        if weak:
            out.append(Finding("testability", SURFACE, f"{ac.id}: {weak}", ref=ac.id))
        # Vague-adjective blocklist (KLC-089): a whole-AC-body quality adjective
        # with no measurable criterion nearby is surfaced. Whole-word only, and
        # skipped when the body already carries a number (a quantified target).
        if not _MEASURABLE_RE.search(ac.body):
            for m in _VAGUE_ADJ_RE.finditer(ac.body):
                out.append(Finding(
                    "testability", SURFACE,
                    f"{ac.id}: unquantified vague adjective {m.group(1)!r} — "
                    f"add a measurable criterion",
                    ref=ac.id))
    return out


def _check_what_not_how(text: str) -> list[Finding]:
    out: list[Finding] = []
    for heading in (("goals",), ("acceptance",), ("problem", "context")):
        body = _strip_code(_section_body(text, heading))
        for line in body.splitlines():
            # A structured AC legitimately names files/artifacts in its Object or
            # Condition (e.g. "· loads · config/constitution.yml"); exempt the
            # bare file-path cue on AC lines so normal file-subject ACs are not
            # flagged. The stronger HOW cues (using/via/implement, algorithms)
            # still apply — those are real implementation smells even in an AC.
            is_ac = _saoc.parse_ac_line(line) is not None
            for idx, cue in enumerate(_HOW_CUES):
                if is_ac and idx == 0:  # cue[0] is the file-path pattern
                    continue
                m = cue.search(line)
                if m:
                    out.append(Finding(
                        "what-not-how", SURFACE,
                        f"possible implementation detail in a requirement section: {m.group(0)!r}",
                    ))
                    break
    return out


def _check_contradiction(text: str) -> list[Finding]:
    out: list[Finding] = []
    acs = [ac for ac in _saoc.parse_acs(text) if ac.is_wellformed]

    # (Duplicate AC ids are handled — as a BLOCK — by the format dimension.)
    # Antonym action + shared object → POSSIBLE contradiction.
    for i in range(len(acs)):
        for j in range(i + 1, len(acs)):
            a, b = acs[i], acs[j]
            act_a = {w for w in re.findall(r"[a-z]+", a.action.lower())}
            act_b = {w for w in re.findall(r"[a-z]+", b.action.lower())}
            for side_x, side_y in _ANTONYMS:
                opposed = (act_a & side_x and act_b & side_y) or (act_a & side_y and act_b & side_x)
                if opposed and (_keywords(a.object) & _keywords(b.object)):
                    out.append(Finding(
                        "contradiction", SURFACE,
                        f"possible contradiction between {a.id} and {b.id} "
                        f"(opposed actions on a shared object)",
                        ref=f"{a.id},{b.id}",
                    ))
                    break
    return out


def _check_completeness(text: str) -> list[Finding]:
    out: list[Finding] = []
    goals_body = _section_body(text, ("goals",))
    if not goals_body.strip():
        return out
    ac_text = " ".join(ac.body for ac in _saoc.parse_acs(text))
    ac_words = _keywords(ac_text)
    # One goal per non-empty line (bullets or sentences).
    for raw in goals_body.splitlines():
        goal = raw.strip().lstrip("-*0123456789. ").strip()
        if len(goal) < 8:
            continue
        gk = _keywords(goal)
        if gk and not (gk & ac_words):
            snippet = goal if len(goal) <= 60 else goal[:57] + "..."
            out.append(Finding(
                "completeness", SURFACE,
                f"declared goal not obviously covered by any AC: {snippet!r}",
            ))
    return out


def _check_coverage(text: str, track: str) -> list[Finding]:
    """Coverage dimension (HEAVY-style, warn-only — KLC-089 / E-05).

    Surfaces the track-mandatory taxonomy categories the E-02 scan leaves
    under-covered, so a draft spec that skipped a dimension the track requires is
    advised on (never failed) at ack. Single-source (C-001): the categories and
    their Clear / Partial / Missing classification are read ONLY through
    `elicitation.scan_coverage` (which itself reads `coverage_taxonomy.for_track`);
    this function re-parses nothing and re-implements no scan.

    Track-scaling (C-003) is decided HERE from the track passed in: on S only
    Missing categories are surfaced (a Partial dimension is thin but present, so
    it stays quiet on the light track), while on M and L Partial categories are
    surfaced too. XS never reaches here — `coverage` is a HEAVY dimension, gated
    off on XS by `_active_dimensions`.

    Degrade-not-fail (C-002), mirroring `_check_constitution`: `elicitation` is
    imported lazily so its absence degrades HERE. The ENTIRE seam interaction —
    the import, the `scan_coverage` call, AND the result comprehension — lives
    inside the try (exactly like `_check_constitution`, whose comment reads "The
    comprehension MUST live inside the try"): so ANY failure of the seam degrades
    to the single SURFACE note, whether it RAISES or returns something MALFORMED
    (None, a non-iterable, or an element lacking `.status`/`.id`, which would
    raise TypeError/AttributeError only when the comprehension touches it). Every
    OTHER dimension (dispatched independently by `self_check`) still runs. NEVER
    emits a BLOCK: an under-covered spec is a completeness signal for the author
    and the independent reviewer, not an objective authoring defect.
    """
    try:
        import elicitation as _elic  # lazy so absence degrades HERE, not at import
        coverage = _elic.scan_coverage(text, track)
        t = (track or "").strip().upper()
        # S surfaces Missing only; M / L (and any non-S track that reaches here)
        # also surface Partial. The status strings are the elicitation vocabulary.
        flag = {"Missing"} if t == "S" else {"Missing", "Partial"}
        # The comprehension MUST live inside the try: a malformed seam return
        # (None, a non-list, or an element missing `.status`/`.id`) raises only
        # HERE, and degrade-not-fail (C-002) requires that to become the single
        # note, never a crash of the whole self-check.
        return [
            Finding("coverage", SURFACE,
                    f"track-mandatory category {c.id!r} is {c.status} — consider covering it",
                    ref=c.id)
            for c in coverage if c.status in flag
        ]
    except Exception as exc:  # ImportError, scan failure, OR a malformed return
        return [Finding("coverage", SURFACE,
                        f"coverage scan unavailable ({exc!r}); completeness surfacing degraded")]


def _check_constitution() -> tuple[list[Finding], list[dict]]:
    """Surface the constitution REVIEW-principle checklist (degrade-safe).

    Returns (findings, checklist). On any failure to load the constitution the
    checklist is empty and a single degraded SURFACE note is returned — never an
    exception.
    """
    try:
        import constitution as _con  # imported lazily so absence degrades here
        principles = _con.review()
        # The comprehension MUST live inside the try: a malformed-but-loadable
        # principle (missing id/statement) raises KeyError here, and degrade-not-
        # fail (itself a constitution principle) requires that to become a note,
        # never a crash of the whole self-check.
        findings = [
            Finding("constitution", SURFACE,
                    f"conformance to review-principle [{p['id']}]: {p['statement']}",
                    ref=p["id"])
            for p in principles
        ]
        return findings, list(principles)
    except Exception as exc:  # FileNotFoundError, ValueError, ImportError, KeyError…
        return (
            [Finding("constitution", SURFACE,
                     f"constitution unavailable ({exc!r}); conformance surfacing degraded")],
            [],
        )


# --- top-level gate ---------------------------------------------------------

def _active_dimensions(track: str) -> set[str]:
    t = (track or "").strip().upper()
    return set(_LIGHT) if t == "XS" else set(_LIGHT | _HEAVY)


def self_check(text: str, track: str | None = None) -> Report:
    """Run the deterministic spec self-check for *track* over spec *text*."""
    report = Report(track=(track or "").strip().upper() or "?")
    active = _active_dimensions(report.track)

    if "format" in active:
        report.findings += _check_format(text)
    if "markers" in active:
        report.findings += _check_markers(text)
    if "testability" in active:
        report.findings += _check_testability(text)
    if "what-not-how" in active:
        report.findings += _check_what_not_how(text)
    if "contradiction" in active:
        report.findings += _check_contradiction(text)
    if "completeness" in active:
        report.findings += _check_completeness(text)
    if "coverage" in active:
        report.findings += _check_coverage(text, report.track)
    if "constitution" in active:
        con_findings, checklist = _check_constitution()
        report.findings += con_findings
        report.constitution_checklist = checklist

    return report


def warn_lines(report: Report) -> list[str]:
    """Compact one-line-per-finding advisory strings for the SURFACED findings.

    Used by the ack path (phase_completion) to print the self-check's surfaced
    issues as warn-only advisories. The constitution checklist is collapsed to a
    single count line so a routine ack is not buried under every principle.
    """
    lines: list[str] = []
    for f in report.surfaced:
        if f.dimension == "constitution":
            continue
        lines.append(f"spec-self-check[{f.dimension}]: {f.message}")
    con = [f for f in report.surfaced if f.dimension == "constitution"]
    if con:
        if report.constitution_checklist:
            lines.append(
                f"spec-self-check[constitution]: {len(report.constitution_checklist)} "
                f"review-principle(s) to consider (run spec_selfcheck for the checklist)"
            )
        else:
            lines.append(f"spec-self-check[constitution]: {con[0].message}")
    return lines


def gate(text: str, track: str | None = None) -> tuple[bool, str]:
    """`(ok, message)` adapter in the phase_completion style.

    ok is False only when a BLOCK finding is present. The message lists blocking
    issues first, then a short surfaced-count summary.
    """
    rep = self_check(text, track)
    if rep.blocking:
        msg = "; ".join(f.message for f in rep.blocking)
        return False, f"spec self-check: {msg}"
    if rep.surfaced:
        return True, f"spec self-check: {len(rep.surfaced)} item(s) surfaced for review"
    return True, ""


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="deterministic spec self-check gate")
    ap.add_argument("--file", required=True)
    ap.add_argument("--track", default="M")
    args = ap.parse_args()
    rep = self_check(Path(args.file).read_text(encoding="utf-8"), args.track)
    print(json.dumps({
        "track": rep.track,
        "ok": rep.ok,
        "blocking": [f.__dict__ for f in rep.blocking],
        "surfaced": [f.__dict__ for f in rep.surfaced],
    }, indent=2, ensure_ascii=False))
    raise SystemExit(0 if rep.ok else 1)
