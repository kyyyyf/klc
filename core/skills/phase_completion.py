#!/usr/bin/env python3
"""phase_completion.py — artifact-based phase completion detection.

Default behaviour: for any phase that declares `outputs` in phases.yml,
check that every listed output file exists and is non-empty.

Discovery and acceptance-test-plan additionally validate frontmatter and
section structure to catch truncated or stub artefacts.
"""
from __future__ import annotations

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
                meta["blast_radius"] = {
                    "available": True,
                    "external_dependents": info.get("external_dependents", []),
                }
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

    # Approaches+pick gate (KLC-032): M/L discovery must record ≥2 approaches and a pick in spec.md.
    if not _spec_structure.has_min_approaches(spec_text):
        return False, "spec.md: fewer than 2 approaches — Socratic protocol requires ≥2 before pick"
    if not _spec_structure.recorded_pick(spec_text):
        return False, "spec.md: no recorded pick — add 'Picked: <approach>' before acking"

    # All checks passed — extract risk_tags from spec.md frontmatter into meta.
    # KLC-062: this is a write, so it is gated on the persisting (ack) path only;
    # read-only callers (remind) pass persist=False and leave meta.json untouched.
    if persist:
        _sync_risk_tags(ticket)
    _advisories = list(_spec_warnings)
    if _spec_structure.has_decompose_signal(spec_text):
        _advisories.append("DISCOVERY_DECOMPOSE: consider decomposing across subsystems before building")
    _advisories += _spec_review_advisories(ticket, persist)
    return True, "; ".join(_advisories)


def can_complete_acceptance_test_plan(ticket: str, *, persist: bool = True) -> tuple[bool, str]:
    """Check if acceptance-test-plan phase artifacts are complete.

    Args:
        persist: when True (default, the ack path) the independent-reviewer seam
            records its findings to `test-plan-review-findings.json`. Read-only
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
    _advisories = _testplan_coverage_gate(ticket)

    # Independent test-plan reviewer (KLC-085 reusing KLC-084's seam): surface the
    # fresh reviewer's routed decisions_to_confirm + a collapsed findings count at
    # the SAME ack decision gate. Warn-only / fail-open, exactly like the spec
    # reviewer at discovery ack. Threads `persist` so a read-only probe writes nothing.
    _advisories += _testplan_review_advisories(ticket, persist)

    # All checks passed
    return True, "; ".join(_advisories)


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
    `test-plan-review-findings.json` (KLC-062 discipline). Track-scaled and
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


def _implplan_review_advisories(ticket: str, persist: bool) -> list[str]:
    """Surface the INDEPENDENT impl-plan reviewer's outputs at the ack (KLC-094).

    The THIRD binding of KLC-084's generic seam — the exact analogue of
    `_spec_review_advisories` / `_testplan_review_advisories`, one artifact further
    right. It reuses the seam (via `implplan_review.consume`, bound to
    `IMPL_PLAN_REVIEW`) to route the reviewer's `decisions_to_confirm[]` into the
    SAME advisory stream the operator already reads at the ack that finalizes
    `impl-plan.md` — a `decision`-level gate — and to surface a collapsed count of
    the OBJECTIVE `findings[]`. No new gate is introduced. Findings are recorded to
    `impl-plan-review-findings.json` for the build agent (`core/agents/impl.md`) to
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

    # Approaches+pick gate (KLC-032): S-track must have ≥2 approaches and a recorded pick.
    # XS is exempt (short tasks don't require a formal options artifact).
    if track == "S":
        _opts_path = ticket_dir / "options-lite.md"
        if not _opts_path.exists():
            return False, "options-lite.md: missing — S-track must record ≥2 approaches and a pick"
        _opts_text = _opts_path.read_text(encoding="utf-8")
        if not _spec_structure.has_min_approaches(_opts_text):
            return False, "options-lite.md: fewer than 2 approaches — Socratic protocol requires ≥2 before pick"
        if not _spec_structure.recorded_pick(_opts_text):
            return False, "options-lite.md: no recorded pick — add 'Picked: <approach>' before acking"

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
    _advisories = list(_spec_warnings)
    if _spec_structure.has_decompose_signal(text):
        _advisories.append("DISCOVERY_DECOMPOSE: consider decomposing across subsystems before building")
    if _spec_structure.has_upgrade_m_signal(text):
        _advisories.append("DISCOVERY_LITE_UPGRADE_M: scope exceeds S — re-route via 'klc retrack <KEY> M'")
    _advisories += _spec_review_advisories(ticket, persist)
    # Independent impl-plan reviewer (KLC-094): discovery-lite is the ack that
    # FINALIZES impl-plan.md for the S track, so surface the reviewer's outputs here,
    # symmetric with the spec reviewer above. Track-scaled + degrade-safe in the seam.
    _advisories += _implplan_review_advisories(ticket, persist)
    return True, "; ".join(_advisories)


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
    """Check if build phase artifacts are complete.

    Requires build-log.md to exist, be non-empty, and contain an ## Evidence
    section with at least one non-empty fenced block (KLC-038).

    Also verifies red-before-green commit ordering for each behaviour step
    in impl-plan.md (KLC-039).  Steps marked ``RED: not applicable`` are exempt.
    Pass *repo* to override the git repository used for commit attribution
    (defaults to the current working directory).

    ``persist`` distinguishes the real ack path (True) from a read-only probe
    (False: ``klc remind`` / gate-policy advisory collection on every prompt). On
    the probe path the AC-coverage arm runs only the STATIC classification and
    spawns NO pytest (KLC-095 FIX-2) — a per-prompt probe must not execute the
    ticket's tests. The completability decision is otherwise identical.
    """
    import re as _re
    import tdd_order as _tdd_order

    ticket_dir = klc_ticket_meta_file(ticket).parent
    build_log_path = ticket_dir / "build-log.md"

    if not build_log_path.exists():
        return False, "Missing build-log.md"
    if build_log_path.stat().st_size == 0:
        return False, "build-log.md is empty"

    text = build_log_path.read_text(encoding="utf-8")

    # Find ## Evidence heading (level-2 only).
    evidence_match = _re.search(r"^## Evidence\b", text, _re.MULTILINE)
    if not evidence_match:
        return False, "build-log.md: missing ## Evidence section — append evidence of each acceptance check before acking"

    # Find at least one non-empty fenced block after ## Evidence.
    after_evidence = text[evidence_match.end():]
    # Stop at the next level-2 heading so we don't bleed into later sections.
    next_h2 = _re.search(r"^## ", after_evidence, _re.MULTILINE)
    evidence_section = after_evidence[:next_h2.start()] if next_h2 else after_evidence

    fence_content_re = _re.compile(r"```[^\n]*\n(.*?)```", _re.DOTALL)
    evidence_ok = any(
        m.group(1).strip() for m in fence_content_re.finditer(evidence_section)
    )
    if not evidence_ok:
        return False, "build-log.md: ## Evidence section has no non-empty fenced block — paste the command and its output inside a fenced block"

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
    advisories: list[str] = []
    try:
        import ac_test_coverage as _acov
        track = (_lc.read_meta_ro(ticket) or {}).get("track", "")
        # run_tests=persist: the scoped pytest runs only on the real ack path; the
        # read-only probe does the static classification with no pytest (FIX-2).
        rep = _acov.check(ticket, track, repo, run_tests=persist)
        if rep.block_reason:
            return False, f"AC coverage: {rep.block_reason}"
        advisories += _acov.warn_lines(rep)
    except Exception as e:
        # degrade-not-fail: a coverage-check surprise never BLOCKS the ack — but it must
        # be OBSERVABLE (a silently-skipped gate could ack an M/L build with operators
        # unaware AC coverage never ran), so surface a degraded advisory (Codex P2).
        advisories.append(
            f"ac-coverage: check did not run — {type(e).__name__} (AC coverage unverified)")

    return True, "; ".join(advisories)


def can_complete(ticket: str, phase_id: str, *, persist: bool = True) -> tuple[bool, str]:
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


def _committed(repo=None) -> tuple[set, set]:
    """Return (committed MODULE names, committed PATHS) for the branch vs origin/main
    (merge-base), used to restrict drift to the ticket's COMMITTED change — an
    uncommitted operator WIP is thus never surfaced (KLC-096 retrospective C-001).
    Merge-base unavailable → (set(), set()) (surface nothing); never raises."""
    if repo is None:
        # Run git in the PROJECT_ROOT checkout, not the caller's cwd — an installed
        # `klc` shim launched elsewhere would otherwise get an empty committed set and
        # silently suppress all committed drift (codex P2; CLAUDE.md PROJECT_ROOT rule).
        try:
            from core.shared.paths import project_root
            repo = project_root()
        except Exception:
            repo = None
    base = _git(["merge-base", "HEAD", "origin/main"], repo) or _git(["merge-base", "HEAD", "main"], repo)
    if not base:
        return set(), set()
    out = _git(["diff", "--name-only", base, "HEAD"], repo)
    paths = {p for p in out.split("\n") if p.strip() and not p.startswith(".klc/")}
    modules_data = _load_modules()
    mods: set = set()
    for p in paths:
        r = _mm.file_to_module(p, modules_data)
        if r.get("primary_module"):
            mods.add(r["primary_module"])
        else:
            # Shared file (no primary): scope_delta reports shared drift by member
            # module, so include member_of or the module arrow suppresses it (codex P2).
            mods.update(r.get("member_of") or [])
    return mods, paths


def _drift_advisories(ticket: str, persist: bool) -> list[str]:
    """Surface the drift-check report (KLC-096) at the integrate ack (KLC-098 D-03).

    Surface-only and degrade-not-fail: any failure degrades to a single advisory
    note; this NEVER blocks and NEVER raises. Scope-drift is restricted to the
    COMMITTED branch diff — drifted modules by NAME∩NAME, orphan files by PATH∩PATH —
    so an uncommitted WIP never surfaces. `persist=True` writes drift-report.json (via
    write_report — the ONLY writer); a read-only probe (persist=False) computes the
    report without writing. Track-scaled: full on M/L, cascade-on-signal on S
    (a coordination/risk-tag signal), skip on XS. Fail-OPEN: an unknown/unreadable
    track runs, since surfacing is safe."""
    # Track-scale first. FAIL-OPEN: any error — a malformed/non-string track, an
    # unreadable meta — falls through to RUNNING (surfacing is safe and never blocks), so
    # the should_run call cannot raise past the never-raise guarantee (review MEDIUM/C-002).
    try:
        _meta = _lc.read_meta_ro(ticket)
        _track = _meta.get("track")
        _skip = bool(_track) and not _spec_review.should_run(
            _track, {"risk_tags": _meta.get("risk_tags") or []}
        )
    except Exception:
        _skip = False
    if _skip:
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
        # persist=True → write_report persists drift-report.json; persist=False →
        # compare computes without writing the report (KLC-062 read-only-probe discipline).
        rep = _drift.write_report(ticket) if persist else _drift.compare(ticket)
        scope = dict(rep.get("scope_drift") or {})
        steps = rep.get("step_without_commit") or {}
        mods, paths = _committed()
        surfaced_mods = [m for m in (scope.get("drifted_modules") or []) if m in mods]
        surfaced_orphans = [o for o in (scope.get("orphan_files") or []) if o in paths]

        lines: list[str] = []
        if scope.get("skipped"):
            lines.append(f"drift scope skipped: {scope['skipped']}")
        if surfaced_mods:
            lines.append(f"scope-drift modules: {', '.join(sorted(surfaced_mods))}")
        if surfaced_orphans:
            lines.append(f"scope-drift orphan files: {', '.join(sorted(surfaced_orphans))}")
        if steps.get("skipped"):
            lines.append(f"step-commit check skipped: {steps['skipped']}")
        if steps.get("flagged"):
            lines.append(f"steps without a commit: {', '.join(steps['flagged'])}")
        return lines
    except Exception as exc:  # noqa: BLE001 — surface-only: never propagate / never block
        return [f"drift-check: skipped — {type(exc).__name__} (unverified)"]
    finally:
        if _meta_snap is not None:
            try:
                if _meta_path.read_bytes() != _meta_snap:
                    _meta_path.write_bytes(_meta_snap)
            except Exception:
                pass


def _drift_review_advisories(ticket: str, persist: bool) -> list[str]:
    """Surface the INDEPENDENT drift-reviewer's outputs at the integrate ack (KLC-099).

    The FOURTH binding of KLC-084's seam — the judgment complement to KLC-098's
    deterministic `_drift_advisories`. Delegates to `drift_review.consume` (bound to
    DRIFT_CHECK), which routes the reviewer's `decisions_to_confirm[]` + a collapsed
    findings count into the ack's advisory lines and records findings to
    `drift-review-findings.json` ONLY when `persist` is True (a read-only probe surfaces
    without writing). Fail-open / surface-only: never blocks, and any error degrades to a
    single note — the seam's degrade-not-fail plus this guard mean it never raises."""
    try:
        tdir = klc_ticket_meta_file(ticket).parent
        meta = _lc.read_meta_ro(ticket)
        adv, _ = _drift_review.consume(
            tdir, meta.get("track"), {"risk_tags": meta.get("risk_tags") or []}, persist=persist
        )
        return adv
    except Exception as exc:  # noqa: BLE001 — surface-only: never propagate / never block
        return [f"drift-review: skipped — {type(exc).__name__}"]


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
        _adv = _drift_advisories(ticket, persist) + _drift_review_advisories(ticket, persist)
        return True, "; ".join(_adv)

    if not phase.outputs:
        return True, ""

    ticket_dir = klc_ticket_meta_file(ticket).parent
    for rel in phase.outputs:
        path = ticket_dir / rel
        if not path.exists():
            return False, f"Missing {rel}"
        if path.stat().st_size == 0:
            return False, f"{rel} is empty"

    # Plan-completeness gate (KLC-036): if impl-plan.md is an output of this phase,
    # it must have no violations.
    _advisories: list[str] = []
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
        _advisories += _implplan_review_advisories(ticket, persist)

    return True, "; ".join(_advisories)


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
