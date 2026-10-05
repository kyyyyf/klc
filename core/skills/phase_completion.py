#!/usr/bin/env python3
"""phase_completion.py — artifact-based phase completion detection.

Default behaviour: for any phase that declares `outputs` in phases.yml,
check that every listed output file exists and is non-empty.

Discovery and acceptance-test-plan additionally validate frontmatter and
section structure to catch truncated or stub artefacts.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent
sys.path.insert(0, str(_project_root))
from core.shared.paths import klc_ticket_meta_file  # noqa: E402
import re  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import track_classifier as _tc  # noqa: E402
import spec_selfreview as _spec_selfreview  # noqa: E402
import spec_selfcheck as _spec_selfcheck  # noqa: E402
import spec_review as _spec_review  # noqa: E402
import testplan_review as _testplan_review  # noqa: E402
import implplan_review as _implplan_review  # noqa: E402
import spec_structure as _spec_structure  # noqa: E402
import impl_plan_check as _impl_plan_check  # noqa: E402
import plan_quality as _plan_quality  # noqa: E402
import drift_check as _drift  # noqa: E402  (KLC-098: report-only drift-check core)
import module_membership as _mm  # noqa: E402  (KLC-098: file→module resolver, KLC-066)
import drift_review as _drift_review  # noqa: E402  (KLC-099: DRIFT_CHECK ReviewKind seam)
import advisories as _adv  # noqa: E402  (KLC-117: the one advisory aggregator)
import provenance as _provenance  # noqa: E402  (KLC-116: the design-ack provenance gate)
import module_vocabulary as _mv  # noqa: E402  (KLC-111: the one vocabulary/mapper module)
import retrieval_eval as _reval  # noqa: E402  (KLC-110: report-only retrieval scorer)


def _provenance_gate_records(ticket: str, persist: bool) -> tuple[str, list[dict]]:
    """`(block_message, advisory_records)` for the KLC-116 design-ack gate.

    Reads track read-only regardless of `persist` — the gate's own decision
    never writes anything; `persist` only threads through to keep the same
    read-only contract every other seam in this module honours. Degrade-not-
    fail (C-004): a crash of `provenance.design_gate` itself never blocks —
    it becomes one degraded advisory record instead.
    """
    try:
        track = (_lc.read_meta_ro(ticket) or {}).get("track", "")
        block, warns = _provenance.design_gate(ticket, track)
    except Exception as exc:                          # noqa: BLE001
        return "", [{"source": "provenance", "severity": "medium",
                    "code": "provenance.degraded",
                    "message": (f"provenance: design gate did not run — "
                                f"{type(exc).__name__} (unverified)"),
                    "ref": ""}]
    records = [{"source": "provenance", "severity": "info",
               "code": "provenance.warn", "message": w, "ref": ""} for w in warns]
    return block, records


def _vocabulary_records(ticket: str) -> list[dict]:
    """One `medium` advisory record per out-of-vocabulary `affected_modules`
    entry (KLC-111 AC-14/AC-15); exactly one `info` record when the module
    index cannot be read (AC-16). Never blocks the ack — this is a pure
    producer, degrade-not-fail by construction (C-004)."""
    data, reason = _mv.load_modules()
    if data is None:
        return [{"source": "scope-vocabulary", "severity": "info",
                 "code": "scope-vocabulary.index-unavailable",
                 "message": f"module vocabulary unchecked — {reason}", "ref": ""}]
    vocab = _mv.vocabulary(data)
    planned = _lc.read_meta_ro(ticket).get("affected_modules") or []
    out = []
    for name in _mv.unknown_names(planned, data):
        hit = _mv.nearest(name, vocab)
        tail = f"did you mean {hit!r}?" if hit else "no candidate found in the current vocabulary"
        out.append({"source": "scope-vocabulary", "severity": "medium",
                    "code": "scope-vocabulary.unknown-module",
                    "message": f"affected_modules entry {name!r} is not a module name — {tail}",
                    "ref": name})
    return out


def can_complete_discovery(ticket: str, *, persist: bool = True) -> tuple[bool, str]:
    """Check if discovery phase artifacts are complete for manual ack.

    Args:
        persist: when True (default, the ack path), completion side effects are
            persisted to meta.json — the floor-guard downgrade audit and the
            risk_tags sync. Read-only callers (`klc remind`, gate-policy advisory)
            pass persist=False so the completability *decision* is unchanged but
            NOTHING is written (KLC-062 AC-1/AC-3).

    Returns:
        (success, error_message)
        success=True: artifacts complete, can advance to ack-needed
        success=False: missing artifacts, error_message describes what's missing
    """
    ticket_dir = klc_ticket_meta_file(ticket).parent
    spec_path = ticket_dir / "spec.md"

    # Check spec.md exists
    if not spec_path.exists():
        return False, "Missing spec.md"

    # Read once; reused by structural checks and the self-review gate below.
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
        lines = spec_text.splitlines()

        # Must start with ---
        if not lines or lines[0].strip() != "---":
            return False, "spec.md: missing frontmatter (must start with '---')"

        # Find closing ---
        frontmatter_end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                frontmatter_end = i
                break

        if frontmatter_end is None:
            return False, "spec.md: incomplete frontmatter (no closing '---')"

        # Parse frontmatter for required fields
        frontmatter = {}
        for line in lines[1:frontmatter_end]:
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()

        # Check ticket field matches
        spec_ticket = frontmatter.get("ticket", "")
        if spec_ticket != ticket:
            return False, f"spec.md: ticket field '{spec_ticket}' doesn't match directory '{ticket}'"

        # Check required frontmatter fields
        required_fields = ["kind", "authority"]
        for field in required_fields:
            if not frontmatter.get(field):
                return False, f"spec.md: missing frontmatter field '{field}'"

        # Check required sections exist
        content = "\n".join(lines[frontmatter_end+1:])
        required_sections = ["## Goals", "## Acceptance Criteria", "## Estimate"]
        for section in required_sections:
            if section not in content:
                return False, f"spec.md: missing required section '{section}'"

    except OSError as e:
        return False, f"Cannot read spec.md: {e}"

    # Check meta.json fields
    try:
        # KLC-062: read-only callers (persist=False) must not trigger a
        # legacy-phase migration write-back here; the in-memory migration still
        # applies so the completion decision is unchanged.
        meta = _lc.read_meta(ticket, persist_migration=persist)

        # Check track
        if not meta.get("track"):
            return False, "meta.json: missing 'track' field"

        # Check estimate
        estimate = meta.get("estimate")
        if not estimate:
            return False, "meta.json: missing 'estimate' field"

        # Validate estimate structure
        required_estimate_fields = ["complexity", "uncertainty", "risk", "manual", "total"]
        if not isinstance(estimate, dict):
            return False, "meta.json: 'estimate' must be an object"

        for field in required_estimate_fields:
            if field not in estimate:
                return False, f"meta.json: estimate missing field '{field}'"

        # Check affected_modules (can be empty array, but must exist)
        if "affected_modules" not in meta:
            return False, "meta.json: missing 'affected_modules' field"

        # Check layer
        if not meta.get("layer"):
            return False, "meta.json: missing 'layer' field"

    except Exception as e:
        return False, f"Cannot read/parse meta.json: {e}"

    # Floor guard (KLC-028): reject unjustified downgrades below route_hint.
    route_hint = meta.get("route_hint", "")
    track = meta.get("track", "")
    _TRACK_ORDER_LOCAL = {"XS": 0, "S": 1, "M": 2, "L": 3}
    if (route_hint in _TRACK_ORDER_LOCAL and track in _TRACK_ORDER_LOCAL
            and _TRACK_ORDER_LOCAL[track] < _TRACK_ORDER_LOCAL[route_hint]):
        # Operator retrack (KLC-027) is the sanctioned escape hatch; its audit
        # lives in phase_history. Never block it here.
        if meta.get("track_source") != "operator":
            from core.shared.paths import klc_index_dir
            import json as _json
            modules_path = klc_index_dir() / "modules.json"
            try:
                modules_index = _json.loads(modules_path.read_text(encoding="utf-8"))
            except Exception:
                modules_index = {}
            affected = meta.get("affected_modules") or []
            safe, info = _tc.is_downgrade_safe(affected, modules_index)
            if not safe:
                reason = info.get("reason", "blast-radius unavailable")
                return (
                    False,
                    f"{ticket}: track {track!r} is below intake floor {route_hint!r} "
                    f"but blast-radius is not low ({reason}); "
                    f"raise the track or use `klc retrack`",
                )
            # AC-3: persist the audit trail so retrospective can verify the evidence.
            # KLC-062: only on the persisting (ack) path — a read-only probe must
            # not write, even though the downgrade-safety decision above still ran.
            if persist:
                meta["track_source"] = "discovery"
                _lc.write_meta(ticket, meta)

    # Self-review gate (KLC-033): reject specs with placeholder/conflict/stub violations.
    _sr = _spec_selfreview.scan_spec(spec_text)
    if _sr:
        v = _sr[0]
        return False, f"spec.md self-review: {v['class']} at offset {v['offset']} — fix before ack"

    # Spec self-check gate (KLC-083): RUN the full deterministic gate at ack. It
    # BLOCKS only on rep.blocking — unresolved [NEEDS CLARIFICATION] markers and
    # duplicate AC ids (objective defects). Format / testability / WHAT-not-HOW /
    # contradiction / completeness and the constitution checklist are SURFACED as
    # warn-only advisories (returned in the message), so legacy pre-SAOC specs are
    # not hard-failed (rigor-scales-by-track). An operator can ack past a
    # KNOWINGLY-deferred marker by setting meta.deferred_markers (mirrors the
    # KLC-027 retrack escape hatch); the deferred marker is then surfaced, not silenced.
    _block, _spec_warnings = _spec_quality_gate(spec_text, meta)
    if _block:
        return False, _block

    # Bug shape gate (KLC-176): kind bug needs the four bug sections + a regression-test AC.
    _bug_block = _bug_shape_block(meta, spec_text)
    if _bug_block:
        return False, _bug_block

    # Approaches+pick gate (KLC-032, KLC-176): M/L discovery reads both from the
    # spec.md `## Approaches` section.
    _appr_block = _approaches_block(spec_text)
    if _appr_block:
        return False, _appr_block

    # All checks passed — extract risk_tags from spec.md frontmatter into meta.
    # KLC-062: this is a write, so it is gated on the persisting (ack) path only;
    # read-only callers (remind) pass persist=False and leave meta.json untouched.
    if persist:
        _sync_risk_tags(ticket)
    _decompose_records: list[dict] = []
    if _spec_structure.has_decompose_signal(spec_text):
        _decompose_records.append({
            "source": "discovery", "severity": "medium", "code": "discovery.decompose",
            "message": "DISCOVERY_DECOMPOSE: consider decomposing across subsystems before building",
            "ref": ""})
    _sources = [
        ("spec-self-check", _spec_warnings),
        ("discovery", _decompose_records),
        ("spec-review", _spec_review_records(ticket, persist)),
        ("scope-vocabulary", _vocabulary_records(ticket)),
    ]
    _records, _summary = _adv.finish(ticket, "discovery", _sources, persist)
    return True, _summary


def can_complete_acceptance_test_plan(ticket: str, *, persist: bool = True) -> tuple[bool, str]:
    """Check if acceptance-test-plan phase artifacts are complete.

    Args:
        persist: when True (default, the ack path) the independent-reviewer seam
            records its findings to `findings.json` (kind test-plan-review). Read-only
            callers (`klc remind`, gate-policy advisory) pass False so the check
            surfaces the same advisories but writes NOTHING (KLC-062 discipline).
            The deterministic coverage gate never writes, so it is unaffected.

    Returns:
        (success, error_message)
    """
    ticket_dir = klc_ticket_meta_file(ticket).parent
    test_plan_path = ticket_dir / "test-plan.md"

    # Check test-plan.md exists
    if not test_plan_path.exists():
        return False, "Missing test-plan.md"

    # Check test-plan.md has valid frontmatter
    try:
        text = test_plan_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Must start with ---
        if not lines or lines[0].strip() != "---":
            return False, "test-plan.md: missing frontmatter (must start with '---')"

        # Find closing ---
        frontmatter_end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                frontmatter_end = i
                break

        if frontmatter_end is None:
            return False, "test-plan.md: incomplete frontmatter (no closing '---')"

        # Check required sections exist
        content = "\n".join(lines[frontmatter_end+1:])
        required_sections = ["## Acceptance coverage", "## Edge cases"]
        for section in required_sections:
            if section not in content:
                return False, f"test-plan.md: missing required section '{section}'"

    except OSError as e:
        return False, f"Cannot read test-plan.md: {e}"

    # Independent test-plan coverage review (KLC-085): RUN the deterministic
    # adversarial-coverage gate and SURFACE its findings as warn-only advisories —
    # like the code reviewer's findings, NOT a new blocking gate (the epic forbids
    # one; an uncovered AC is already a phase-failure via the test-planner). It maps
    # each spec SAOC AC to a planned test and flags uncovered ACs / happy-path-only
    # plans / gate-ACs missing a negative test. Track-scaled (XS skip, S coverage-
    # only, M/L full) and degrade-safe inside the skill, so it never fails an ack.
    # Independent test-plan reviewer (KLC-085 reusing KLC-084's seam): surface the
    # fresh reviewer's routed decisions_to_confirm + a collapsed findings count at
    # the SAME ack decision gate. Warn-only / fail-open, exactly like the spec
    # reviewer at discovery ack. Threads `persist` so a read-only probe writes nothing.
    _sources = [
        ("testplan-coverage", _testplan_coverage_gate(ticket)),
        ("testplan-review", _testplan_review_records(ticket, persist)),
    ]
    _records, _summary = _adv.finish(ticket, "acceptance-test-plan", _sources, persist)
    return True, _summary


def _sync_risk_tags(ticket: str) -> None:
    """Read risk_tags from spec.md frontmatter and write into meta.json."""
    ticket_dir = klc_ticket_meta_file(ticket).parent
    spec_path = ticket_dir / "spec.md"
    try:
        lines = spec_path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            return
        fm_end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        if fm_end is None:
            return
        risk_tags: list[str] = []
        for line in lines[1:fm_end]:
            m = re.match(r"risk_tags\s*:\s*\[([^\]]*)\]", line.strip())
            if m:
                raw = m.group(1)
                risk_tags = [v.strip().strip("'\"") for v in raw.split(",") if v.strip()]
                break
        meta = _lc.read_meta(ticket)
        meta["risk_tags"] = risk_tags
        from core.shared.paths import klc_ticket_meta_file as _meta_file
        import json as _json
        _meta_file(ticket).write_text(
            _json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        pass  # non-fatal: risk_tags will just be absent


def _spec_review_advisories(ticket: str, persist: bool) -> list[str]:
    """Surface an independent spec reviewer's outputs at ack (KLC-084).

    Routes the reviewer's `decisions_to_confirm[]` into the SAME advisory stream
    the operator already reads at the discovery/design ack — a `decision`-level
    gate — so the human resolves them there, and surfaces a collapsed count of the
    OBJECTIVE `findings[]` so that primary output is not silent. No new gate is
    introduced. Findings are recorded to disk for the build phase to assess, but
    ONLY on the persisting ack path: `persist` is threaded into `consume` so a
    read-only probe (`klc remind` / gate-policy signal collection) surfaces without
    writing. Track-scaled and degrade-safe: absent reviewer output on a
    review-expected track surfaces one note; on a skip/no-signal track it is
    silent; nothing here ever fails the ack.

    Reads meta read-only (KLC-062: an advisory probe must not persist a legacy
    phase migration). Only `risk_tags` is available as an escalation signal at the
    spec phase — there is no diff yet (so no sentinel/scope-expansion signal), so
    those are left to callers that have them via `spec_review.should_run`.
    """
    try:
        meta = _lc.read_meta_ro(ticket)
        ticket_dir = klc_ticket_meta_file(ticket).parent
        track = meta.get("track", "")
        signals = {"risk_tags": meta.get("risk_tags") or []}
        advisories, _findings = _spec_review.consume(
            ticket_dir, track, signals, persist=persist
        )
        return advisories
    except Exception:
        return []  # degrade-not-fail: the review seam never blocks an ack


def _spec_review_records(ticket: str, persist: bool) -> list[dict]:
    """Record-shaped twin of `_spec_review_advisories` (KLC-117): the aggregator
    source for the KLC-084 spec-review seam, via `spec_review.consume_records` so
    a routed decision is high and a findings summary/schema/degraded note is
    high-or-medium/medium (Q-003) — not a legacy-wrapped info record.
    `_spec_review_advisories` itself is untouched (its own direct callers keep
    the `list[str]` contract)."""
    try:
        meta = _lc.read_meta_ro(ticket)
        ticket_dir = klc_ticket_meta_file(ticket).parent
        track = meta.get("track", "")
        signals = {"risk_tags": meta.get("risk_tags") or []}
        records, _findings = _spec_review.consume_records(
            ticket_dir, track, signals, persist=persist
        )
        return records
    except Exception:
        return []  # degrade-not-fail: the review seam never blocks an ack


def _testplan_coverage_gate(ticket: str) -> list[str]:
    """Run the KLC-085 independent test-plan coverage review for the ack path.

    Returns warn-only advisory lines (never blocks — mirrors the code reviewer,
    adds no new gate). The review is track-scaled and degrade-safe inside the
    skill; a defensive guard here keeps any surprise from ever failing an ack.
    """
    try:
        rep = _testplan_review.run(ticket)
        return _testplan_review.warn_lines(rep)
    except Exception:
        return []  # degrade-not-fail: a coverage-review crash never blocks ack


def _testplan_review_advisories(ticket: str, persist: bool) -> list[str]:
    """Surface the INDEPENDENT test-plan reviewer's outputs at the ack (KLC-085).

    The exact analogue of `_spec_review_advisories`, one artifact further right:
    it reuses KLC-084's generic seam (via `testplan_review.consume`, bound to
    `TEST_PLAN_REVIEW`) to route the reviewer's `decisions_to_confirm[]` into the
    SAME advisory stream the operator already reads at ack — a `decision`-level
    gate — and to surface a collapsed count of the OBJECTIVE `findings[]`. No new
    gate is introduced. Findings are recorded to disk for the build phase to assess
    ONLY on the persisting ack path: `persist` is threaded into `consume`, so a
    read-only probe (`klc remind` / gate-policy) surfaces WITHOUT writing
    `findings.json` (kind test-plan-review) (KLC-062 discipline). Track-scaled and
    degrade-safe inside the seam; nothing here ever fails the ack.

    This is separate from `_testplan_coverage_gate`, which runs 085's own
    DETERMINISTIC coverage heuristics. Both are surfaced, neither blocks.
    """
    try:
        meta = _lc.read_meta_ro(ticket)
        ticket_dir = klc_ticket_meta_file(ticket).parent
        track = meta.get("track", "")
        signals = {"risk_tags": meta.get("risk_tags") or []}
        advisories, _findings = _testplan_review.consume(
            ticket_dir, track, signals, persist=persist
        )
        return advisories
    except Exception:
        return []  # degrade-not-fail: the review seam never blocks an ack


def _testplan_review_records(ticket: str, persist: bool) -> list[dict]:
    """Record-shaped twin of `_testplan_review_advisories` (KLC-117) — same
    Q-003 severity mapping as `_spec_review_records`, via
    `testplan_review.consume_records`."""
    try:
        meta = _lc.read_meta_ro(ticket)
        ticket_dir = klc_ticket_meta_file(ticket).parent
        track = meta.get("track", "")
        signals = {"risk_tags": meta.get("risk_tags") or []}
        records, _findings = _testplan_review.consume_records(
            ticket_dir, track, signals, persist=persist
        )
        return records
    except Exception:
        return []  # degrade-not-fail: the review seam never blocks an ack


def _implplan_review_advisories(ticket: str, persist: bool) -> list[str]:
    """Surface the INDEPENDENT impl-plan reviewer's outputs at the ack (KLC-094).

    The THIRD binding of KLC-084's generic seam — the exact analogue of
    `_spec_review_advisories` / `_testplan_review_advisories`, one artifact further
    right. It reuses the seam (via `implplan_review.consume`, bound to
    `IMPL_PLAN_REVIEW`) to route the reviewer's `decisions_to_confirm[]` into the
    SAME advisory stream the operator already reads at the ack that finalizes
    `impl-plan.md` — a `decision`-level gate — and to surface a collapsed count of
    the OBJECTIVE `findings[]`. No new gate is introduced. Findings are recorded to
    `findings.json` (kind impl-plan-review) for the build agent (`core/agents/impl.md`) to
    assess ONLY on the persisting ack path: `persist` is threaded into `consume`, so
    a read-only probe (`klc remind` / gate-policy) surfaces WITHOUT writing (KLC-062
    discipline). Track-scaled (M/L full, S cascade-on-signal, XS skip — and XS
    produces no impl-plan.md) and degrade-safe inside the seam; nothing here ever
    fails the ack.

    Reads meta read-only (an advisory probe must not persist a legacy phase
    migration). Wired at BOTH acks that finalize impl-plan.md: discovery-lite (S) and
    the design phase (M/L, via `_can_complete_generic` when impl-plan.md is an output).
    """
    try:
        meta = _lc.read_meta_ro(ticket)
        ticket_dir = klc_ticket_meta_file(ticket).parent
        track = meta.get("track", "")
        signals = {"risk_tags": meta.get("risk_tags") or []}
        advisories, _findings = _implplan_review.consume(
            ticket_dir, track, signals, persist=persist
        )
        return advisories
    except Exception:
        return []  # degrade-not-fail: the review seam never blocks an ack


def _implplan_review_records(ticket: str, persist: bool) -> list[dict]:
    """Record-shaped twin of `_implplan_review_advisories` (KLC-117) — same
    Q-003 severity mapping as `_spec_review_records`, via
    `implplan_review.consume_records`."""
    try:
        meta = _lc.read_meta_ro(ticket)
        ticket_dir = klc_ticket_meta_file(ticket).parent
        track = meta.get("track", "")
        signals = {"risk_tags": meta.get("risk_tags") or []}
        records, _findings = _implplan_review.consume_records(
            ticket_dir, track, signals, persist=persist
        )
        return records
    except Exception:
        return []  # degrade-not-fail: the review seam never blocks an ack


def _spec_quality_gate(spec_text: str, meta: dict) -> tuple[str, list[str]]:
    """Run the KLC-083 spec self-check for the ack path.

    Returns (block_message, warn_lines). `block_message` is non-empty only when a
    BLOCK finding survives (unresolved markers — unless meta.deferred_markers is
    set — and duplicate AC ids). Everything else, plus any deferred marker, is
    returned as warn-only advisory lines. Degrade-safe: the self-check never
    raises, but a defensive guard keeps a surprise from ever failing an ack.
    """
    track = meta.get("track", "")
    try:
        rep = _spec_selfcheck.self_check(spec_text, track)
    except Exception:
        return "", []  # degrade-not-fail: a self-check crash never blocks ack
    defer = bool(meta.get("deferred_markers"))
    blocking = [f for f in rep.blocking if not (f.dimension == "markers" and defer)]
    block_msg = f"spec.md self-check: {blocking[0].message}" if blocking else ""
    warnings = _spec_selfcheck.warn_lines(rep)
    if defer:
        for f in rep.blocking:
            if f.dimension == "markers":
                warnings.append(f"spec-self-check[markers:deferred]: {f.message}")
    return block_msg, warnings


def _is_legacy_layout(meta: dict) -> bool:
    """True for a ticket created before the KLC-176 layout (no `meta.layout`):
    only those may still be judged on options-lite.md / design/options.md."""
    return not meta.get("layout")


def _bug_shape_block(meta: dict, spec_text: str) -> str:
    """Block message when a kind-bug spec lacks the bug sections / regression-test AC (KLC-176)."""
    if meta.get("kind") != "bug" and _spec_selfreview.spec_kind(spec_text) != "bug":
        return ""
    vs = _spec_selfreview.bug_shape_violations(spec_text)
    if not vs:
        return ""
    missing = ", ".join(v["phrase"] for v in vs)
    return f"spec.md: kind bug requires {missing} — add before ack"


def _approaches_block(text: str, *, section: bool = True, label: str = "spec.md") -> str:
    """Block message unless `text` has >=2 approaches and a pick (KLC-176).

    section=True reads the `## Approaches` body of spec.md text; section=False
    judges the text as-is (legacy options-lite.md fallback).
    """
    body = text
    if section:
        body = _spec_structure.approaches_text(text)
        if body is None:
            return "spec.md: missing '## Approaches' section — record ≥2 approaches and 'Picked: <approach>'"
    if not _spec_structure.has_min_approaches(body):
        return f"{label}: fewer than 2 approaches — Socratic protocol requires ≥2 before pick"
    if not _spec_structure.recorded_pick(body):
        return f"{label}: no recorded pick — add 'Picked: <approach>' before acking"
    return ""


def can_complete_discovery_lite(ticket: str, *, persist: bool = True) -> tuple[bool, str]:
    """Check if discovery-lite artifacts are complete (XS/S spec).

    Stricter than generic: verifies spec sections, estimate.total vs track,
    affected_modules >= 1, and risk_tags present in frontmatter.

    `persist` mirrors `can_complete_discovery`: when False (read-only callers)
    the risk_tags sync is skipped so meta.json is left byte-identical (KLC-062).
    """
    ticket_dir = klc_ticket_meta_file(ticket).parent
    spec_path = ticket_dir / "spec.md"

    if not spec_path.exists():
        return False, "Missing spec.md"

    # Read once; reused by structural checks and the self-review gate below.
    try:
        text = spec_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Check required sections
        required_sections = ["## Goals", "## Acceptance Criteria", "## Estimate"]
        for section in required_sections:
            if section not in text:
                return False, f"spec.md: missing required section '{section}'"
        if "## Affected" not in text:
            return False, "spec.md: missing required section '## Affected' or '## Affected modules'"
        if "- [ ]" not in text and "- [x]" not in text.lower():
            return False, "spec.md: Acceptance Criteria has no checklist items"

        # Check risk_tags in frontmatter (AC-E2: must be present, not just valid)
        import re as _re
        fm_end = None
        if lines and lines[0].strip() == "---":
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    fm_end = i
                    break
        if fm_end is not None:
            fm_text = "\n".join(lines[1:fm_end])
            if "risk_tags" not in fm_text:
                return False, "spec.md: missing risk_tags frontmatter field (set to [] for low-risk changes)"

    except OSError as e:
        return False, f"Cannot read spec.md: {e}"

    try:
        # KLC-062: same read-only guard as can_complete_discovery — suppress the
        # legacy-migration write-back when persist=False (decision unchanged).
        meta = _lc.read_meta(ticket, persist_migration=persist)
        track = meta.get("track")
        if not track:
            return False, "meta.json: missing 'track' field"
        if track not in ("XS", "S"):
            return False, f"meta.json: discovery-lite expects XS or S track, got {track!r}"

        estimate = meta.get("estimate")
        if not estimate:
            return False, "meta.json: missing 'estimate' field"

        total = estimate.get("total")
        if total is None:
            return False, "meta.json: estimate missing 'total' field"

        # AC-A4: total must agree with track
        if track == "XS" and total > 2:
            return False, f"meta.json: XS track requires estimate.total <= 2, got {total}"
        if track == "S" and total > 5:
            return False, f"meta.json: S track requires estimate.total <= 5, got {total}"

        # AC-A4: affected_modules must be non-empty
        affected = meta.get("affected_modules") or []
        if len(affected) < 1:
            return False, "meta.json: affected_modules must have at least 1 entry for discovery-lite"

    except Exception as e:
        return False, f"Cannot read meta.json: {e}"

    # Self-review gate (KLC-033): reject specs with placeholder/conflict/stub violations.
    _sr = _spec_selfreview.scan_spec(text)
    if _sr:
        v = _sr[0]
        return False, f"spec.md self-review: {v['class']} at offset {v['offset']} — fix before ack"

    # Spec self-check gate (KLC-083): RUN the full deterministic gate at ack.
    # BLOCKS only on unresolved [NEEDS CLARIFICATION] markers and duplicate AC ids;
    # the rest is surfaced as warn-only advisories (see can_complete_discovery).
    _spec_block, _spec_warnings = _spec_quality_gate(text, meta)
    if _spec_block:
        return False, _spec_block

    # Bug shape gate (KLC-176): applies to XS and S alike.
    _bug_block = _bug_shape_block(meta, text)
    if _bug_block:
        return False, _bug_block

    # Approaches+pick gate (KLC-032, KLC-176): S-track reads the spec.md `## Approaches`
    # section. XS is exempt. Read-only fallback: an old ticket that has no such section
    # but carries options-lite.md is judged on that file, so archived tickets still pass.
    if track == "S":
        _legacy = ticket_dir / "options-lite.md"
        if (_spec_structure.approaches_text(text) is None and _legacy.exists()
                and _is_legacy_layout(meta)):
            _appr_block = _approaches_block(
                _legacy.read_text(encoding="utf-8"), section=False, label="options-lite.md")
        else:
            _appr_block = _approaches_block(text)
        if _appr_block:
            return False, _appr_block

    # Plan-completeness gate (KLC-036): S-track must have impl-plan.md (it is a
    # discovery-lite output for S); XS does not produce one.  When present, the
    # plan must be free of violations.
    _impl_plan_path = ticket_dir / "impl-plan.md"
    if track == "S" and not _impl_plan_path.exists():
        return False, "Missing impl-plan.md (required for S-track; produced by discovery-lite)"
    if _impl_plan_path.exists():
        _impl_plan_text = _impl_plan_path.read_text(encoding="utf-8")
        _violations = _impl_plan_check.impl_plan_violations(_impl_plan_text)
        if _violations:
            return False, f"impl-plan.md: {_violations[0]}"
        _api_refs = _plan_quality.unresolved_api_refs(_impl_plan_text)
        if _api_refs:
            return False, f"impl-plan.md: {_api_refs[0]}"

    # All checks passed — sync risk_tags from spec.md into meta.json.
    # KLC-062: gated to the persisting (ack) path; read-only callers skip the write.
    if persist:
        _sync_risk_tags(ticket)
    _signal_records: list[dict] = []
    if _spec_structure.has_decompose_signal(text):
        _signal_records.append({
            "source": "discovery", "severity": "medium", "code": "discovery.decompose",
            "message": "DISCOVERY_DECOMPOSE: consider decomposing across subsystems before building",
            "ref": ""})
    if _spec_structure.has_upgrade_m_signal(text):
        _signal_records.append({
            "source": "discovery", "severity": "medium", "code": "discovery.upgrade-m",
            "message": "DISCOVERY_LITE_UPGRADE_M: scope exceeds S — re-route via 'klc retrack <KEY> M'",
            "ref": ""})
    # Independent impl-plan reviewer (KLC-094): discovery-lite is the ack that
    # FINALIZES impl-plan.md for the S track, so surface the reviewer's outputs here,
    # symmetric with the spec reviewer above. Track-scaled + degrade-safe in the seam.
    # KLC-116: on S the same load-bearing check SURFACES rather than blocks (AC-8;
    # `design_gate` never returns a block message for a track outside M/L, so the
    # block half of `_provenance_gate_records` is unreachable here — asserted, not
    # re-implemented); on XS `design_gate` itself computes nothing (AC-9).
    _, _prov_records = _provenance_gate_records(ticket, persist)
    _sources = [
        ("spec-self-check", _spec_warnings),
        ("discovery", _signal_records),
        ("spec-review", _spec_review_records(ticket, persist)),
        ("impl-plan-review", _implplan_review_records(ticket, persist)),
        ("provenance", _prov_records),
        ("scope-vocabulary", _vocabulary_records(ticket)),
    ]
    _records, _summary = _adv.finish(ticket, "discovery-lite", _sources, persist)
    return True, _summary


def _impl_plan_steps(ticket_dir: Path) -> list[dict]:
    """Parse impl-plan.md and return step metadata.

    Delegates to impl_plan_check.parse_impl_plan_steps (single parser) and
    adapts the output to the shape this function's callers expect:
    Each entry: {"step": int, "red_not_applicable": bool}.
    Returns [] when impl-plan.md is absent or unreadable.
    """
    import impl_plan_check as _ipc
    impl_plan_path = ticket_dir / "impl-plan.md"
    if not impl_plan_path.exists():
        return []
    try:
        text = impl_plan_path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for s in _ipc.parse_impl_plan_steps(text):
        step_num = int(s["id"].split("-")[1])
        # Tolerate markdown emphasis around the field name (`**RED**:`),
        # the form the design agent's impl-plan template actually emits.
        red_m = re.search(r"(?i)\bRED\**:(.+)", s["body"])
        red_val = red_m.group(1).strip().lower() if red_m else ""
        out.append({
            "step": step_num,
            "red_not_applicable": "not applicable" in red_val,
        })
    return out


def can_complete_build(ticket: str, repo: Path | None = None, *,
                       persist: bool = True) -> tuple[bool, str]:
    """Check if build phase artifacts are complete (KLC-174).

    The ack READS state and executes no stored command: every impl-plan step must
    be green with a recorded verify in build/steps.json (`step_state.check_build`,
    recomputed from git + the plan; the file is never trusted), the red-before-green
    order must hold (KLC-039; ``RED: not applicable`` steps are exempt) and AC→test
    coverage must hold (KLC-095). build-log.md is optional free notes.

    Pass *repo* to override the git repository used for commit attribution
    (defaults to the current working directory).

    ``persist`` distinguishes the real ack path (True) from a read-only probe
    (False: ``klc remind`` / gate-policy advisory collection on every prompt). On
    the probe path the AC-coverage arm runs only the STATIC classification and
    spawns NO pytest (KLC-095 FIX-2). Unusual on purpose: the coverage arm keeps
    running the framework's own scoped pytest on the real ack (operator decision);
    only STORED shell commands are never re-executed.
    """
    import time as _time
    import tdd_order as _tdd_order
    import settings as _settings
    import step_state as _step_state

    _verify_deadline = _time.monotonic() + _settings.verify_arm_budget()

    ticket_dir = klc_ticket_meta_file(ticket).parent

    # Red-before-green ordering gate (KLC-039): check each behaviour step.
    for step_info in _impl_plan_steps(ticket_dir):
        if step_info["red_not_applicable"]:
            continue
        ok, reason = _tdd_order.verify_step(ticket, step_info["step"], repo)
        if not ok:
            return False, f"TDD order: {reason}"

    # AC→implemented-test coverage gate (KLC-095, V-02): the execution double of
    # the KLC-085 plan-time coverage check. Each SAOC AC must map to a REAL,
    # collected, passing implemented test. An objective miss (no implemented test
    # at all) BLOCKS on M/L — symmetric to the tdd_order branch above — unless the
    # operator set meta.deferred_ac_coverage; drift / weak signals / S-misses /
    # degradation SURFACE as advisories threaded into the success message. The
    # guard keeps degrade-not-fail: a coverage-check crash never blocks the ack.
    _acov_records: list[dict] = []
    try:
        import ac_test_coverage as _acov
        track = (_lc.read_meta_ro(ticket) or {}).get("track", "")
        # run_tests=persist: the scoped pytest runs only on the real ack path; the
        # read-only probe does the static classification with no pytest (FIX-2).
        rep = _acov.check(ticket, track, repo, run_tests=persist, deadline=_verify_deadline)
        if rep.block_reason:
            return False, f"AC coverage: {rep.block_reason}"
        _acov_records = _acov.advisory_records(rep)
    except Exception as e:
        # degrade-not-fail: a coverage-check surprise never BLOCKS the ack — but it must
        # be OBSERVABLE (a silently-skipped gate could ack an M/L build with operators
        # unaware AC coverage never ran), so surface a degraded advisory (Codex P2).
        _acov_records = [{"source": "ac-coverage", "severity": "medium",
                          "code": "ac-coverage.degraded",
                          "message": (f"ac-coverage: check did not run — "
                                      f"{type(e).__name__} (AC coverage unverified)"),
                          "ref": ""}]

    # KLC-174: every plan step green with a valid recorded verify (reads only).
    ok, reason = _step_state.check_build(ticket, repo, persist=persist)
    if not ok:
        return False, f"build steps: {reason}"

    _sources = [("ac-coverage", _acov_records)]
    _records, _summary = _adv.finish(ticket, "build", _sources, persist)
    return True, _summary


_RECORDING_PHASES = frozenset({"build", "review", "manual"})   # KLC-128 Q-001
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def integrate_evaluators_run(ticket: str) -> bool:
    """KLC-128: the integrate evaluators' track gate (full on M/L, cascade on
    S with an escalation signal, skip on XS or an unescalated S) — mirrors the
    inline gate `_drift_advisories`/`_retrieval_advisories` already run, so the
    pre-merge recording (below) and the two producers agree on which tracks
    ever pay a git cost. Fail-OPEN, like the gate it mirrors: an unreadable or
    malformed track runs rather than silently skipping."""
    try:
        meta = _lc.read_meta_ro(ticket)
        track = meta.get("track")
        return not (bool(track) and not _spec_review.should_run(
            track, {"risk_tags": meta.get("risk_tags") or []}))
    except Exception:
        return True


def _project_repo():
    """The PROJECT_ROOT checkout — the same resolution `_committed()` uses,
    so the recorded range and the live diff always agree on which repo they
    read git from."""
    try:
        from core.shared.paths import project_root
        return project_root()
    except Exception:
        return None


def _live_merge_base(repo) -> str:
    """KLC-166 step-1 (D-002): the ONE live merge-base rule (KLC-128):
    `origin/main`, else local `main`. Used by `_committed`,
    `_pre_merge_range_patch` and `ticket_diff_range` so the rule has exactly
    one expression instead of three inline copies. Empty string on any
    failure (never raises — delegates to `_git`, which already degrades
    that way)."""
    return (_git(["merge-base", "HEAD", "origin/main"], repo)
            or _git(["merge-base", "HEAD", "main"], repo))


def _non_klc_paths(name_only: str) -> set:
    """KLC-166 step-1 (D-002): the `.klc/`-path filter shared by
    `_committed`, `_pre_merge_range_patch`, `_resolve_ground_truth` and
    `ticket_diff_range` — given a `git diff --name-only` style newline-joined
    listing, return the set of non-empty paths that do NOT start with
    `.klc/`."""
    return {p for p in name_only.split("\n") if p.strip() and not p.startswith(".klc/")}


def _pre_merge_range_patch(ticket: str, phase_id: str) -> dict | None:
    """KLC-128 D-201/D-202: stage `{base, head, recorded_at_phase,
    recorded_at}` for the pre-merge range, or return None to stage nothing.

    Up to four git calls (a KLC-129 branch-mismatch `rev-parse
    --abbrev-ref HEAD`, `merge-base`, a `main` fallback only when
    `origin/main` is absent, and `rev-parse HEAD`), gated first by
    `integrate_evaluators_run` so a track-skipped ack never pays them. Never
    raises — a git failure, a non-hex result, or `HEAD` sitting on a
    DIFFERENT ticket's branch (KLC-129 D-002 — see `_head_branch_mismatch`)
    all degrade to "stage nothing", never a verdict change."""
    if not integrate_evaluators_run(ticket):
        return None
    if _head_branch_mismatch(ticket) is not None:
        return None  # KLC-129 D-002: never record another ticket's diff
    repo = _project_repo()
    base = _live_merge_base(repo)
    head = _git(["rev-parse", "HEAD"], repo)
    if not (_SHA_RE.match(base or "") and _SHA_RE.match(head or "")):
        return None
    out = _git(["diff", "--name-only", base, head], repo)
    if not _non_klc_paths(out):
        return None                       # latest NON-EMPTY range wins (Q-001)
    import datetime as _dt
    return {"base": base, "head": head, "recorded_at_phase": phase_id,
            "recorded_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def can_complete(ticket: str, phase_id: str, *, persist: bool = True) -> tuple[bool, str]:
    """`_can_complete_dispatch`'s verdict, plus (KLC-128 AC-4/AC-5) staging the
    ticket's pre-merge range on a True, persisting verdict at build, review or
    manual. Recording never changes the verdict: any failure inside it is
    swallowed, and a read-only probe (`persist=False`) never reaches it."""
    ok, msg = _can_complete_dispatch(ticket, phase_id, persist=persist)
    if ok and persist and phase_id in _RECORDING_PHASES:
        try:
            patch = _pre_merge_range_patch(ticket, phase_id)
            if patch:
                _lc.stage_meta_patch(ticket, {"pre_merge_range": patch})
        except Exception:
            pass                          # recording never changes a verdict
    return ok, msg


def _can_complete_dispatch(ticket: str, phase_id: str, *, persist: bool = True) -> tuple[bool, str]:
    """Check if a phase can be manually completed based on artifacts.

    Args:
        ticket: ticket key (e.g., "KLC-001")
        phase_id: phase identifier (e.g., "discovery", "build")
        persist: when True (default, ack path) discovery completion may persist
            side effects (risk_tags sync, floor-guard audit) and the
            acceptance-test-plan reviewer seam records its findings. Read-only
            callers (`klc remind`, gate-policy advisory) pass False so the check
            never writes (KLC-062 AC-1). For build, persist=False additionally
            keeps the AC-coverage arm from spawning pytest (KLC-095 FIX-2); the
            generic phases treat the flag as a no-op.

    Returns:
        (success, error_message)
    """
    if phase_id == "discovery":
        return can_complete_discovery(ticket, persist=persist)

    if phase_id == "discovery-lite":
        return can_complete_discovery_lite(ticket, persist=persist)

    if phase_id == "acceptance-test-plan":
        return can_complete_acceptance_test_plan(ticket, persist=persist)

    if phase_id == "build":
        return can_complete_build(ticket, persist=persist)

    # Generic check: every output declared in phases.yml must exist and
    # be non-empty.  Phases with no declared outputs pass immediately
    # (e.g. integrate, observe).
    return _can_complete_generic(ticket, phase_id, persist=persist)


def _git(args: list[str], repo=None) -> str:
    """Run a read-only git command; empty string on any failure (never raises)."""
    import subprocess
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(repo) if repo else None,
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _load_modules() -> dict:
    """Read .klc/index/modules.json ($PROJECT_ROOT-aware); {"modules": []} on failure."""
    import json
    from core.shared.paths import klc_index_dir
    try:
        d = json.loads((klc_index_dir() / "modules.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"modules": d}
    except Exception:
        return {"modules": []}


def _committed(repo=None, *, cache: dict | None = None) -> tuple[set, set]:
    """Return (committed MODULE names, committed PATHS) for the branch vs origin/main
    (merge-base), used to restrict drift to the ticket's COMMITTED change — an
    uncommitted operator WIP is thus never surfaced (KLC-096 retrospective C-001).
    Merge-base unavailable → (set(), set()) (surface nothing); never raises.

    `cache` (KLC-110 review round 1, step-10, D-110-11, additive/optional):
    when given, the parsed `modules.json` this call loads is ALSO stashed
    under `cache['modules_data']`, so a sibling producer sharing the same
    per-ack cache (`_modules_data_cached`) reuses it at zero extra I/O
    instead of reading the file a second time."""
    if repo is None:
        # Run git in the PROJECT_ROOT checkout, not the caller's cwd — an installed
        # `klc` shim launched elsewhere would otherwise get an empty committed set and
        # silently suppress all committed drift (codex P2; CLAUDE.md PROJECT_ROOT rule).
        # KLC-128 step-8 (review INFO): reuses `_project_repo()` — the SAME
        # resolution the ground-truth resolver uses — instead of a second,
        # duplicated try/except doing the identical thing.
        repo = _project_repo()
    base = _live_merge_base(repo)
    if not base:
        return set(), set()
    out = _git(["diff", "--name-only", base, "HEAD"], repo)
    paths = _non_klc_paths(out)
    return _paths_to_modules(paths, cache), paths


def _paths_to_modules(paths, cache: dict | None) -> set:
    """KLC-128 step-2: the module-mapping half of `_committed`, factored out
    so `_resolve_ground_truth`'s recorded-range leg can apply the SAME rule
    (and the same `cache['modules_data']` stash, KLC-110 D-110-11) to a diff
    that never went through `_committed` itself."""
    if cache is not None and "modules_data" in cache:
        modules_data = cache["modules_data"]
    else:
        modules_data = _load_modules()
        if cache is not None:
            cache["modules_data"] = modules_data
    mods: set = set()
    for p in paths:
        r = _mm.file_to_module(p, modules_data)
        if r.get("primary_module"):
            mods.add(r["primary_module"])
        else:
            # Shared file (no primary): scope_delta reports shared drift by member
            # module, so include member_of or the module arrow suppresses it (codex P2).
            mods.update(r.get("member_of") or [])
    return mods


_R_NO_RANGE = "no recorded pre-merge range for this ticket"

def _ticket_prefix_re(ticket: str) -> re.Pattern[str]:
    """KLC-129 D-005 (review round 1, external MEDIUM #2): build the
    ticket-key pattern from the ACKED ticket's own project prefix (`KLC` in
    `KLC-129`), never a hardcoded `KLC-`. `intake.py`'s `DEFAULT_KEY_RE`
    (`^[A-Z][A-Z0-9]+-\\d+$`) is this project's only other definition of
    "what a ticket key looks like", and every project this framework is
    deployed to as a plugin picks its own prefix — a hardcoded `KLC-` made
    the guard a silent no-op (fail-open, never worse, but never firing
    either) anywhere else. `\\d+` immediately after the prefix and hyphen,
    plus `\\b` word boundaries on both ends, keeps `KLC-12` and `KLC-129`
    distinct (neither is a substring match of the other) — the same
    numeric-prefix-confusion guarantee the original hardcoded pattern gave,
    now for whatever prefix `ticket` itself uses."""
    prefix = ticket.rsplit("-", 1)[0]
    return re.compile(rf"\b{re.escape(prefix)}-\d+\b", re.IGNORECASE)


def _head_branch_mismatch(ticket: str, repo=None) -> str | None:
    """KLC-129 D-001: `None` when the current branch cannot be tied to a
    DIFFERENT ticket (proceed exactly as today — fail-open); a reason string
    when the branch name embeds a ticket key other than *ticket*. Never
    raises. This is the ONE detector every wired site (the ground-truth
    resolver, the pre-merge-range recorder, the sentinel scan) shares, so an
    ack issued while `HEAD` sits on another ticket's branch (raw.md F-001)
    degrades the same way everywhere instead of silently scoring that
    ticket's diff as this one's.

    KLC-129 D-006 (review round 1, external MEDIUM #3): when the branch
    names the ACKED ticket's own key — even alongside another same-prefix
    key, e.g. a follow-up branch `feature/klc-129-followup-klc-128` — this
    is the ticket's OWN branch, not a mismatch. Only a branch that names at
    least one same-prefix key and NOT the ticket's own is a mismatch;
    checking membership before discarding (rather than discarding the
    ticket's own hit and testing what is left) is what makes "own key
    present" win even when other keys are also present."""
    try:
        if repo is None:
            repo = _project_repo()
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    except Exception:
        return None
    if not branch or branch == "HEAD":
        return None
    hits = {m.upper() for m in _ticket_prefix_re(ticket).findall(branch)}
    if not hits or ticket.upper() in hits:
        return None
    return f"HEAD is on {branch!r}, which names {sorted(hits)}, not {ticket}"


def _gt(mods, paths, source, reason) -> dict:
    return {"modules": set(mods), "paths": set(paths), "source": source, "reason": reason}


def _read_pre_merge_range(ticket: str) -> tuple[dict | None, str]:
    """KLC-128 D-203: validate the recorded range, never raise. A missing or
    malformed object means 'no usable range' (AC-8, AC-12) — the SPECIFIC
    reason names what was wrong, so a degrade never reads as a bare generic
    skip."""
    rng = (_lc.read_meta_ro(ticket) or {}).get("pre_merge_range")
    if rng is None:
        return None, _R_NO_RANGE
    if not isinstance(rng, dict):
        return None, f"recorded pre-merge range is malformed: not an object ({type(rng).__name__})"
    for key in ("base", "head"):
        if not _SHA_RE.match(str(rng.get(key) or "")):
            return None, f"recorded pre-merge range is malformed: {key!r} is missing or not a 40-hex sha"
    return rng, ""


def _is_ancestor(base: str, head: str, repo) -> bool:
    """KLC-128 step-7 (review round 1, MEDIUM): `base` must actually PRECEDE
    `head` in this repository's history — a crafted or mistaken pair of
    unrelated-but-resolvable 40-hex shas in `meta.json` (klc-state is
    multi-writer) must never silently become a `recorded-range` ground
    truth. `base` is an ancestor of `head` iff their merge-base equals
    `base` (the standard git idiom) — used instead of `git merge-base
    --is-ancestor`, which communicates its answer ONLY through the exit
    code, a channel `_git()`'s stdout-based contract cannot see (D-128-3).
    This keeps the check on the SAME `_git` seam every other call here goes
    through, so the KLC-128 git-invocation counting passthrough (which wraps
    `phase_completion._git`) still sees it as one `merge-base` call. Never
    raises: any git failure (a bad/absent object included) resolves to
    `False`, which degrades exactly like a genuine non-ancestor pair (also
    D-128-3 — see the two review-fix test updates in build-log.md)."""
    mb = _git(["merge-base", base, head], repo)
    return bool(mb) and mb == base


def _validated_recorded_range(ticket: str, repo) -> tuple[dict | None, str, bool]:
    """KLC-166 step-5 (review round 1, F-3): the recorded-range validation
    shared by `_resolve_ground_truth` and `ticket_diff_range` — read
    `meta.pre_merge_range` (`_read_pre_merge_range`), validate ancestry
    (`_is_ancestor`), and require at least one changed path outside
    `.klc/` (`_non_klc_paths`). Never raises (each helper it calls already
    degrades that way). The SAME two git calls in the SAME order as
    before this extraction (KLC-128 git-call-count bound unchanged).

    On success: `({"base", "head", "paths"}, "", False)`, *paths* being the
    `_non_klc_paths` result the caller needs (`_resolve_ground_truth`
    turns it into modules; `ticket_diff_range` does not need it); the
    third element is meaningless on success and always `False`.

    On failure: `(None, reason, no_range)`, where *reason* names exactly
    what was wrong, UNPREFIXED, and *no_range* is `True` only when
    `_read_pre_merge_range` itself found nothing usable to validate
    (missing or malformed — there was never a range to check ancestry or
    resolvability against), `False` when a range WAS recorded but failed
    the ancestry or resolvability check below.

    KLC-166 step-6 (review round 2, F-1): this distinction is why the
    return widened from a 2-tuple — `_resolve_ground_truth` must apply its
    KLC-129 branch-mismatch reason ONLY when *no_range* is `True`; a
    recorded-but-invalid range reports its OWN reason even when `HEAD` also
    sits on another ticket's branch (see that function's docstring). This
    was the historical, pre-step-5 precedence; step-5's extraction had
    collapsed all three failures onto the same `(None, reason)` shape and
    so silently lost it. `ticket_diff_range` does not need the
    distinction (it has no mismatch leg to prioritise over) and ignores
    the third element, keeping its own historical `"{live_why}; {reason}"`
    wording unchanged."""
    rng, why = _read_pre_merge_range(ticket)
    if rng is None:
        return None, why, True
    if not _is_ancestor(rng["base"], rng["head"], repo):
        return None, (f"recorded pre-merge range base is not an ancestor of head: "
                      f"{rng['base']}..{rng['head']}"), False
    out = _git(["diff", "--name-only", rng["base"], rng["head"]], repo)
    rpaths = _non_klc_paths(out)
    if not rpaths:                                   # D-204: no extra probe call
        return None, (f"recorded pre-merge range {rng['base']}..{rng['head']} "
                      "is not resolvable in this clone"), False
    return {"base": rng["base"], "head": rng["head"], "paths": rpaths}, "", False


def _resolve_ground_truth(ticket: str, cache: dict) -> dict:
    """KLC-128 D-203: the ONE ground-truth derivation at the integrate ack —
    live, then recorded, then none. Never raises, and never falls back to a
    key-grep/reflog derivation (AC-8).

    KLC-129 D-001/D-002: before trusting the live diff, check whether `HEAD`
    sits on a DIFFERENT ticket's branch (F-001) — if so, the live diff is
    never trusted (`source` is never `"live-merge-base"` in that case) and
    resolution falls straight through to the ticket's own recorded range, or
    to `"none"` with the mismatch as its reason when no range is recorded
    either.

    KLC-166 step-6 (review round 2, F-1): "when no range is recorded
    either" is load-bearing — the mismatch reason must win ONLY when
    `_validated_recorded_range` found nothing recorded at all (its
    `no_range` flag). A range that IS recorded but fails ancestry or
    resolvability reports THAT reason even while `HEAD` also sits on
    another ticket's branch; the mismatch never hides a bad recorded
    range. step-5's extraction had collapsed this into a bare
    `mismatch or why` for every failure, silently reversing the
    precedence (no test caught it — this step adds one)."""
    try:
        mismatch = _head_branch_mismatch(ticket)          # KLC-129 D-001/D-002
        if mismatch is None:
            mods, paths = _committed(cache=cache)         # today's live rule, unchanged (AC-3)
            if paths:
                return _gt(mods, paths, "live-merge-base", None)
        repo = _project_repo()
        # KLC-128 step-7 (review MEDIUM, AC-8/AC-12): validate ancestry BEFORE
        # diffing — the one extra git call the review ruling allows on this
        # leg (D-128-3 updates the AC-10 bound from <= 3 to <= 4).
        # KLC-166 step-5 (F-3): this whole leg is now the shared
        # `_validated_recorded_range` (also used by `ticket_diff_range`),
        # same two git calls in the same order.
        rng, why, no_range = _validated_recorded_range(ticket, repo)
        if rng is None:
            # KLC-166 step-6 (F-1): mismatch wins only when NOTHING was
            # recorded; a recorded-but-invalid range reports its own reason.
            return _gt((), (), "none", (mismatch or why) if no_range else why)
        return _gt(_paths_to_modules(rng["paths"], cache), rng["paths"], "recorded-range", None)
    except Exception as exc:  # noqa: BLE001 — never propagate (AC-12)
        return _gt((), (), "none", f"ground truth unavailable: {type(exc).__name__}: {exc}")


def ticket_diff_range(ticket: str) -> tuple[dict | None, str]:
    """KLC-166 step-1: the ticket's own committed range for the hand-back
    planner bootstrap (`handback._run_planner`, step-2) — live, then
    recorded, built only from the KLC-128/KLC-129 helpers above (D-002: no
    third copy of the merge-base or mismatch rule). Never raises.

    Live range: `merge-base(HEAD, origin/main or main)..HEAD`, when HEAD is
    not on another ticket's branch (`_head_branch_mismatch`, KLC-129 D-002)
    and that range changes at least one path outside `.klc/` (AC-1).

    Recorded range: `meta.pre_merge_range`, after the same SHA, ancestry and
    non-empty checks `_resolve_ground_truth`'s recorded leg applies (AC-2),
    when the live range is unusable for any reason: HEAD on another
    ticket's branch, no merge-base computable, or no changed path outside
    `.klc/` (spec-review F-6 / test-plan-review F-1).

    Otherwise `(None, reason)`, where *reason* names both legs (AC-3)."""
    try:
        repo = _project_repo()
        live_why = _head_branch_mismatch(ticket, repo)          # C-002
        if live_why is None:
            base, head = _live_merge_base(repo), _git(["rev-parse", "HEAD"], repo)
            if not (_SHA_RE.match(base or "") and _SHA_RE.match(head or "")):
                live_why = "no merge-base of HEAD with origin/main or main"
            elif not _non_klc_paths(_git(["diff", "--name-only", base, head], repo)):
                live_why = f"the live range {base[:12]}..{head[:12]} changes no path outside .klc/"
            else:
                return {"base": base, "head": head, "source": "live-merge-base"}, ""
        # KLC-166 step-5 (F-3): the recorded leg is now the shared
        # `_validated_recorded_range` (also used by `_resolve_ground_truth`),
        # same two git calls in the same order; only the live-leg prefix
        # on the reason is added here. The third element (whether nothing
        # was recorded at all) is `_resolve_ground_truth`'s mismatch-vs-
        # recorded precedence call to make, not this function's — there is
        # no mismatch leg here to prioritise over, so it is ignored.
        rng, why, _no_range = _validated_recorded_range(ticket, repo)
        if rng is None:
            return None, f"{live_why}; {why}"
        return {"base": rng["base"], "head": rng["head"], "source": "recorded-range"}, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"range unavailable: {type(exc).__name__}: {exc}"


_RUN_SCOPE: dict | None = None     # KLC-128 D-205: lives for one outermost ack.run, keyed by ticket


@contextlib.contextmanager
def ground_truth_scope():
    """KLC-128 D-205: a run-scoped cache opened by the OUTERMOST `ack.run`,
    reused by its WORK→ack-needed recursion (a nested entry is a no-op that
    yields the SAME scope), keyed by ticket, and cleared on that outermost
    run's exit. Bounded by construction: it never outlives one `ack.run`
    call, and it never lets one ticket's resolved set leak into another's."""
    global _RUN_SCOPE
    outermost = _RUN_SCOPE is None
    if outermost:
        _RUN_SCOPE = {}
    try:
        yield _RUN_SCOPE
    finally:
        if outermost:
            _RUN_SCOPE = None


def _scope_cache(ticket: str) -> dict:
    """The per-ticket dict inside the currently open `ground_truth_scope()`,
    or a fresh dict when none is open (every caller outside an `ack.run`,
    unaffected — KLC-128 D-205)."""
    return _RUN_SCOPE.setdefault(ticket, {}) if _RUN_SCOPE is not None else {}


def integrate_ground_truth(ticket: str, *, cache: dict | None = None) -> dict:
    """KLC-128 D-205: the one resolver every integrate-ack consumer (the
    drift check, the retrieval evaluator, the `ack.py` scope guard) calls.
    Resolved at most once per *cache* — a pre-warmed KLC-110
    `cache["committed"]` (F-203) is honoured with zero extra git calls. With
    no `cache` given, defaults to the run-scoped `_scope_cache(ticket)` — so
    a caller inside an open `ground_truth_scope()` (the `ack.py` guard) shares
    the SAME resolution the integrate branch above already ran."""
    cache = _scope_cache(ticket) if cache is None else cache
    if "ground_truth" not in cache:
        _pre = cache.get("committed")
        if _pre is not None and _pre[1]:                 # a NON-EMPTY pre-warmed KLC-110 pair
            m, p = _pre
            cache["ground_truth"] = _gt(m, p, "live-merge-base", None)
        else:
            # KLC-128 step-7 (review LOW, AC-3): an ABSENT pre-warmed pair
            # short-circuits above; an EMPTY one must NOT — it only tells us
            # the LIVE diff was empty, never that no recorded range exists,
            # so it falls through to the full resolver, which still consults
            # the recorded range.
            cache["ground_truth"] = _resolve_ground_truth(ticket, cache)
        g = cache["ground_truth"]
        cache.setdefault("committed", (g["modules"], g["paths"]))
    return cache["ground_truth"]


def _committed_cached(cache: dict | None) -> tuple[set, set]:
    """`_committed()` at most ONCE per ack (KLC-110 AC-21, D-216).

    `cache` is a dict the integrate branch creates fresh per ack and threads
    through every advisory producer that needs the committed diff; each
    fills it on first need. A module-level global here would be a stale-diff
    bug across acks and across two tickets scored in one process. Callers
    must resolve this only AFTER their own degrade checks pass (D-214, D-300),
    so a ticket with no usable trace, or a track that skips, adds no git
    invocation at all. `cache=None` (the default for every existing caller)
    falls straight through to an uncached `_committed()` call, so callers
    that never share a cache are unaffected.
    """
    if cache is None:
        return _committed()
    if "committed" not in cache:
        cache["committed"] = _committed(cache=cache)
    return cache["committed"]


def _modules_data_cached(cache: dict | None) -> dict:
    """The parsed `modules.json` this ack has already loaded (KLC-110 review
    round 1, step-10, D-110-11) — reused by the retrieval evaluator's
    colocated-test sibling-confirmation predicate (AC-21 explicitly
    sanctions reading the module map). When `_committed_cached(cache)` has
    already run this ack (the drift producer runs first in `_sources`), the
    SAME dict `_committed()` loaded is already sitting in
    `cache['modules_data']` and this costs zero extra I/O. `cache=None`, or
    a cache `_committed_cached` was never called against (e.g. a track-
    skipped ack that still somehow reaches here), falls back to a direct
    `_load_modules()` call — never a git invocation."""
    if cache is not None and "modules_data" in cache:
        return cache["modules_data"]
    return _load_modules()


def _drift_advisories(ticket: str, persist: bool, *, committed: dict | None = None) -> list[dict]:
    """Surface the drift-check report (KLC-096) at the integrate ack (KLC-098 D-03).

    KLC-117: returns advisory RECORDS (severity medium — Q-003: a scope-drift
    condition or a skipped/degraded arm is medium, never info, because it names
    an unplanned module or an untested step). Surface-only and degrade-not-fail:
    any failure degrades to a single advisory record; this NEVER blocks and NEVER
    raises. Scope-drift is restricted to the COMMITTED branch diff — drifted
    modules by NAME∩NAME, orphan files by PATH∩PATH — so an uncommitted WIP never
    surfaces. `persist=True` goes through write_report, a read-only probe
    (persist=False) through compare; neither writes a report file (KLC-173).
    Track-scaled: full on M/L, cascade-on-signal on S (a coordination/risk-tag signal), skip on XS. Fail-OPEN: an unknown/unreadable
    track runs, since surfacing is safe."""
    # Track-scale first (KLC-128: the one gate `integrate_evaluators_run`
    # shares with the recording seam and the retrieval producer — fail-open,
    # since surfacing is safe and never blocks, review MEDIUM/C-002).
    if not integrate_evaluators_run(ticket):
        return []  # XS skip / S without an escalation signal

    # A read-only probe (persist=False, e.g. `klc remind` / gate-policy) must persist
    # NOTHING — but drift_check.compare → scope_delta.compare → _lc.read_meta can migrate
    # a legacy-phase meta as a side effect. Snapshot meta and restore it after the probe
    # so the read-only guarantee holds regardless of a downstream brick's side effects.
    # The snapshot read is guarded too (a TOCTOU delete/permission error must not raise).
    _meta_path = klc_ticket_meta_file(ticket)
    try:
        _meta_snap = _meta_path.read_bytes() if (not persist and _meta_path.exists()) else None
    except Exception:
        _meta_snap = None
    try:
        # KLC-128: resolve the ground truth BEFORE calling the brick, so the
        # SAME object both scores the drift section and labels the report
        # (AC-6, AC-7). `committed is None` (only test callers, F-202) keeps
        # today's EXACT one-argument call (D-208).
        if committed is not None:
            gt = integrate_ground_truth(ticket, cache=committed)
            mods, paths = gt["modules"], gt["paths"]
            # KLC-173: write_report returns the report and persists nothing; the
            # summary flows into the integrate advisories.
            rep = (_drift.write_report(ticket, ground_truth=gt) if persist
                  else _drift.compare(ticket, ground_truth=gt))
        else:
            mods, paths = _committed_cached(committed)   # D-208: exact legacy call
            rep = _drift.write_report(ticket) if persist else _drift.compare(ticket)
        scope = dict(rep.get("scope_drift") or {})
        steps = rep.get("step_without_commit") or {}
        surfaced_mods = [m for m in (scope.get("drifted_modules") or []) if m in mods]
        surfaced_orphans = [o for o in (scope.get("orphan_files") or []) if o in paths]

        def _rec(code: str, message: str) -> dict:
            return {"source": "drift-check", "severity": "medium",
                    "code": f"drift-check.{code}", "message": message, "ref": ""}

        records: list[dict] = []
        if scope.get("skipped"):
            records.append(_rec("skipped", f"drift scope skipped: {scope['skipped']}"))
        if surfaced_mods:
            records.append(_rec("scope-drift-modules",
                                f"scope-drift modules: {', '.join(sorted(surfaced_mods))}"))
        if surfaced_orphans:
            records.append(_rec("scope-drift-orphans",
                                f"scope-drift orphan files: {', '.join(sorted(surfaced_orphans))}"))
        if steps.get("skipped"):
            records.append(_rec("step-commit-skipped",
                                f"step-commit check skipped: {steps['skipped']}"))
        if steps.get("flagged"):
            records.append(_rec("steps-without-commit",
                                f"steps without a commit: {', '.join(steps['flagged'])}"))
        return records
    except Exception as exc:  # noqa: BLE001 — surface-only: never propagate / never block
        return [{"source": "drift-check", "severity": "medium", "code": "drift-check.degraded",
                "message": f"drift-check: skipped — {type(exc).__name__} (unverified)",
                "ref": ""}]
    finally:
        if _meta_snap is not None:
            try:
                if _meta_path.read_bytes() != _meta_snap:
                    _meta_path.write_bytes(_meta_snap)
            except Exception:
                pass


def _drift_review_advisories(ticket: str, persist: bool) -> list[dict]:
    """Surface the INDEPENDENT drift-reviewer's outputs at the integrate ack (KLC-099).

    KLC-117: returns advisory RECORDS via `drift_review.consume_records` (the
    thin delegate to `spec_review.consume_records`), so a routed decision/high
    finding is high and a schema/degraded note is medium (Q-003), matching the
    other three review-binding sources.

    The FOURTH binding of KLC-084's seam — the judgment complement to KLC-098's
    deterministic `_drift_advisories`. Delegates to `drift_review.consume_records`
    (bound to DRIFT_CHECK), which routes the reviewer's `decisions_to_confirm[]`
    + a collapsed findings count into the ack's advisory records and records
    findings to `findings.json` (kind drift-review) ONLY when `persist` is True (a
    read-only probe surfaces without writing). Fail-open / surface-only: never
    blocks, and any error degrades to a single info record — the seam's
    degrade-not-fail plus this guard mean it never raises."""
    try:
        tdir = klc_ticket_meta_file(ticket).parent
        meta = _lc.read_meta_ro(ticket)
        records, _ = _drift_review.consume_records(
            tdir, meta.get("track"), {"risk_tags": meta.get("risk_tags") or []}, persist=persist
        )
        return records
    except Exception as exc:  # noqa: BLE001 — surface-only: never propagate / never block
        return [{"source": "drift-review", "severity": "info",
                "code": "drift-review.degraded",
                "message": f"drift-review: skipped — {type(exc).__name__}", "ref": ""}]


def _retrieval_advisories(ticket: str, persist: bool, *, committed=None) -> list[dict]:
    """Surface the retrieval score at the integrate ack (KLC-110), in the same
    surface-only position as the two drift producers: never blocks, never raises,
    and persist=False stages nothing and writes nothing.

    TRACK-SCALED exactly like _drift_advisories: full on M/L, cascade-on-signal
    on S, skip on XS. Fail-OPEN, since surfacing is safe.
    """
    # GATE 1 — TRACK, first, before anything reads a trace (D-300, revision-2
    # review F-1). _drift_advisories returns [] here, twenty lines before its own
    # _committed() call, so on a skipped track the ack issues ZERO git calls today.
    # Gating only on trace status (revision 2) closed that hole only while traces
    # are degraded; the moment an XS ticket's trace is `ok`, this producer becomes
    # the ack's FIRST _committed() caller and AC-21's bound breaks.
    if not integrate_evaluators_run(ticket):
        return []                      # XS skip / S without an escalation signal
    try:
        _meta = _lc.read_meta_ro(ticket)
    except Exception:
        _meta = {}                     # fail-open: surfacing is safe, cost is not

    _meta_path = klc_ticket_meta_file(ticket)
    try:
        _snap = _meta_path.read_bytes() if (not persist and _meta_path.exists()) else None
    except Exception:
        _snap = None
    try:
        trace = _reval.read_trace(ticket)
        # GATE 2 — DEGRADE, second (D-214). Orthogonal to gate 1, not a substitute
        # for it: this one spares an M ticket whose trace is missing, which the
        # track gate does not, and the track gate spares an XS ticket whose trace
        # is fine, which this one does not. Both, in this order.
        if not trace or trace.get("status") != "ok":
            # KLC-128 AC-9: persist the degraded record too. `evaluate()`
            # returns before it reads the committed sets (D-210), so routing
            # through `consume()` here adds no git call and no module-map
            # read for the TRACE-DEGRADE branch itself.
            #
            # KLC-128 step-8 (review MEDIUM): ACTIVELY resolve via
            # `integrate_ground_truth(ticket, cache=committed)` rather than
            # passively reading `committed.get('ground_truth')` — the old
            # code silently produced an unlabelled record whenever this
            # producer ran BEFORE `_drift_advisories` had populated the
            # shared cache (or was called standalone). `integrate_ground_truth`
            # memoises in `committed`, so this is zero EXTRA cost whenever
            # drift already resolved it this ack (the real `_sources`
            # ordering, drift-check first) — it only pays a real resolution
            # cost the FIRST time anything asks, which is now this call
            # rather than never. `committed is None` (only a test caller
            # with no cache at all) still asks for nothing.
            label = integrate_ground_truth(ticket, cache=committed) if committed is not None else None
            rec = _reval.consume(ticket, trace, set(), set(), _meta.get("track"),
                                 persist=persist, ground_truth=label)
        else:
            # Only now, past BOTH gates, is a git subprocess permissible.
            gt = None
            if committed is not None:
                gt = integrate_ground_truth(ticket, cache=committed)
                mods, paths = gt["modules"], gt["paths"]
            else:
                mods, paths = _committed_cached(committed)   # D-208: exact legacy call
            modules_data = _modules_data_cached(committed)
            rec = _reval.consume(ticket, trace, mods, paths, _meta.get("track"),
                                 persist=persist, modules_data=modules_data,
                                 ground_truth=gt)
        return _reval.advisory_records(ticket, rec)
    except Exception as exc:    # surface-only: never propagate, never block
        return [{"source": "retrieval-eval", "severity": "info",
                 "code": "retrieval-eval.degraded",
                 "message": f"retrieval-eval: skipped — {type(exc).__name__}",
                 "ref": ""}]
    finally:
        if _snap is not None:
            try:
                if _meta_path.read_bytes() != _snap:
                    _meta_path.write_bytes(_snap)
            except Exception:
                pass


_RETRO_HEADINGS = ("What the gates missed", "Token cost by phase", "One process change")
_RETRO_MAX_LINES = 40


def retro_shape_advisories(ticket: str) -> list[dict]:
    """Surface-only (KLC-176 AC-9): a retrospective over 40 lines or without the
    three fixed headings. Never blocks the learn ack; no file means no advisory
    (the generic gate already reports a missing output)."""
    path = klc_ticket_meta_file(ticket).parent / "retrospective.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    msgs = []
    if len(text.splitlines()) > _RETRO_MAX_LINES:
        msgs.append(f"retrospective.md is longer than {_RETRO_MAX_LINES} lines")
    msgs += [f"retrospective.md lacks '## {h}'" for h in _RETRO_HEADINGS
             if f"## {h}" not in text]
    return [{"source": "retro-shape", "severity": "low", "code": "retro.shape",
             "message": m, "ref": ""} for m in msgs]


def _can_complete_generic(ticket: str, phase_id: str, *, persist: bool = True) -> tuple[bool, str]:
    """Check that all phases.yml outputs exist and are non-empty.

    `persist` is threaded through so the independent impl-plan reviewer seam
    (KLC-094) can record its findings on the ack path and stay read-only on an
    advisory probe — it is a no-op for phases whose outputs do not include
    impl-plan.md.
    """
    try:
        ph = _ph.load_phases()
        phase = ph.by_id(phase_id)
    except (KeyError, Exception) as exc:
        return False, f"cannot load phase definition for {phase_id!r}: {exc}"

    # Integrate drift advisories (KLC-098 deterministic + KLC-099 judgment). MUST sit
    # BEFORE the empty-outputs early return — integrate declares `outputs: []`, so the
    # advisory would be unreachable after it. Surface-only: always a completable (True, …).
    if phase_id == "integrate":
        # KLC-110 D-216: one cache dict per ack, threaded through every
        # producer that may need the committed diff, so `_committed()` runs
        # at most once total across drift-check and the retrieval evaluator.
        # KLC-128 D-205: `_scope_cache` returns the SAME per-ticket dict the
        # `ack.py` scope guard reads too, when a `ground_truth_scope()` is
        # open around this whole `ack.run` (a fresh dict otherwise).
        _cache: dict = _scope_cache(ticket)
        _sources = [
            ("drift-check", _drift_advisories(ticket, persist, committed=_cache)),
            ("drift-review", _drift_review_advisories(ticket, persist)),
            ("retrieval-eval", _retrieval_advisories(ticket, persist, committed=_cache)),
        ]
        _records, _summary = _adv.finish(ticket, "integrate", _sources, persist)
        return True, _summary

    if not phase.outputs:
        return True, ""

    ticket_dir = klc_ticket_meta_file(ticket).parent
    try:
        meta = _lc.read_meta_ro(ticket)
    except Exception:
        meta = {}
    for rel in phase.outputs:
        path = ticket_dir / rel
        if rel == "design.md" and not path.exists() and _is_legacy_layout(meta):
            # an in-flight ticket from before KLC-176 still carries design/options.md
            path = ticket_dir / "design" / "options.md"
            rel = "design/options.md" if path.exists() else rel
        if not path.exists():
            return False, f"Missing {rel}"
        if path.stat().st_size == 0:
            return False, f"{rel} is empty"
        if rel == "design.md":
            _opts = _spec_structure.design_options_text(path.read_text(encoding="utf-8"))
            if not _spec_structure.has_min_approaches(_opts or ""):
                return False, "design.md: ## Options needs at least 2 labelled options"
            if not _spec_structure.recorded_pick(_opts or ""):
                return False, "design.md: ## Options has no 'Picked:' line"

    # Plan-completeness gate (KLC-036): if impl-plan.md is an output of this phase,
    # it must have no violations.
    _sources: list[tuple] = []
    if "impl-plan.md" in phase.outputs:
        _impl_plan_path = ticket_dir / "impl-plan.md"
        _impl_plan_text = _impl_plan_path.read_text(encoding="utf-8")
        _violations = _impl_plan_check.impl_plan_violations(_impl_plan_text)
        if _violations:
            return False, f"impl-plan.md: {_violations[0]}"
        _api_refs = _plan_quality.unresolved_api_refs(_impl_plan_text)
        if _api_refs:
            return False, f"impl-plan.md: {_api_refs[0]}"
        # Independent impl-plan reviewer (KLC-094): this phase (design, on M/L) is the
        # ack that FINALIZES impl-plan.md, so surface the fresh reviewer's routed
        # decisions_to_confirm + a collapsed findings count at this ack — the same
        # decision gate, warn-only / fail-open, exactly like the spec reviewer at the
        # discovery ack. Threads `persist` so a read-only probe writes nothing.
        _sources.append(("impl-plan-review", _implplan_review_records(ticket, persist)))
        # KLC-116: an unmeasured load-bearing decision blocks THIS ack on M/L — the
        # phase that finalizes design/options.md. Degrade-not-fail (C-004): a crash
        # of the gate itself never blocks; it only loses the check for this ack.
        _prov_block, _prov_records = _provenance_gate_records(ticket, persist)
        if _prov_block:
            return False, f"design: {_prov_block}"
        _sources.append(("provenance", _prov_records))

    if phase_id == "learn":
        _sources.append(("retro-shape", lambda: retro_shape_advisories(ticket)))

    _records, _summary = _adv.finish(ticket, phase_id, _sources, persist)
    return True, _summary


if __name__ == "__main__":
    # CLI for testing
    import argparse

    ap = argparse.ArgumentParser(description="Check if phase artifacts are complete")
    ap.add_argument("ticket", help="Ticket key")
    ap.add_argument("phase", help="Phase ID (e.g., discovery)")
    args = ap.parse_args()

    success, error = can_complete(args.ticket, args.phase)
    if success:
        print(f"✓ {args.phase} artifacts complete for {args.ticket}")
        sys.exit(0)
    else:
        print(f"✗ {error}", file=sys.stderr)
        sys.exit(1)
