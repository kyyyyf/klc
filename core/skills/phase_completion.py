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
import spec_structure as _spec_structure  # noqa: E402
import impl_plan_check as _impl_plan_check  # noqa: E402
import plan_quality as _plan_quality  # noqa: E402


def can_complete_discovery(ticket: str) -> tuple[bool, str]:
    """Check if discovery phase artifacts are complete for manual ack.

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
        meta = _lc.read_meta(ticket)

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

    # Approaches+pick gate (KLC-032): M/L discovery must record ≥2 approaches and a pick in spec.md.
    if not _spec_structure.has_min_approaches(spec_text):
        return False, "spec.md: fewer than 2 approaches — Socratic protocol requires ≥2 before pick"
    if not _spec_structure.recorded_pick(spec_text):
        return False, "spec.md: no recorded pick — add 'Picked: <approach>' before acking"

    # All checks passed — extract risk_tags from spec.md frontmatter into meta
    _sync_risk_tags(ticket)
    if _spec_structure.has_decompose_signal(spec_text):
        return True, "DISCOVERY_DECOMPOSE: consider decomposing across subsystems before building"
    return True, ""


def can_complete_acceptance_test_plan(ticket: str) -> tuple[bool, str]:
    """Check if acceptance-test-plan phase artifacts are complete.

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

    # All checks passed
    return True, ""


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


def can_complete_discovery_lite(ticket: str) -> tuple[bool, str]:
    """Check if discovery-lite artifacts are complete (XS/S spec).

    Stricter than generic: verifies spec sections, estimate.total vs track,
    affected_modules >= 1, and risk_tags present in frontmatter.
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
        meta = _lc.read_meta(ticket)
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

    # All checks passed — sync risk_tags from spec.md into meta.json
    _sync_risk_tags(ticket)
    if _spec_structure.has_decompose_signal(text):
        return True, "DISCOVERY_DECOMPOSE: consider decomposing across subsystems before building"
    return True, ""


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
        red_m = re.search(r"(?i)\bRED:(.+)", s["body"])
        red_val = red_m.group(1).strip().lower() if red_m else ""
        out.append({
            "step": step_num,
            "red_not_applicable": "not applicable" in red_val,
        })
    return out


def can_complete_build(ticket: str, repo: Path | None = None) -> tuple[bool, str]:
    """Check if build phase artifacts are complete.

    Requires build-log.md to exist, be non-empty, and contain an ## Evidence
    section with at least one non-empty fenced block (KLC-038).

    Also verifies red-before-green commit ordering for each behaviour step
    in impl-plan.md (KLC-039).  Steps marked ``RED: not applicable`` are exempt.
    Pass *repo* to override the git repository used for commit attribution
    (defaults to the current working directory).
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

    return True, ""


def can_complete(ticket: str, phase_id: str) -> tuple[bool, str]:
    """Check if a phase can be manually completed based on artifacts.

    Args:
        ticket: ticket key (e.g., "KLC-001")
        phase_id: phase identifier (e.g., "discovery", "build")

    Returns:
        (success, error_message)
    """
    if phase_id == "discovery":
        return can_complete_discovery(ticket)

    if phase_id == "discovery-lite":
        return can_complete_discovery_lite(ticket)

    if phase_id == "acceptance-test-plan":
        return can_complete_acceptance_test_plan(ticket)

    if phase_id == "build":
        return can_complete_build(ticket)

    # Generic check: every output declared in phases.yml must exist and
    # be non-empty.  Phases with no declared outputs pass immediately
    # (e.g. integrate, observe).
    return _can_complete_generic(ticket, phase_id)


def _can_complete_generic(ticket: str, phase_id: str) -> tuple[bool, str]:
    """Check that all phases.yml outputs exist and are non-empty."""
    try:
        ph = _ph.load_phases()
        phase = ph.by_id(phase_id)
    except (KeyError, Exception) as exc:
        return False, f"cannot load phase definition for {phase_id!r}: {exc}"

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
    if "impl-plan.md" in phase.outputs:
        _impl_plan_path = ticket_dir / "impl-plan.md"
        _impl_plan_text = _impl_plan_path.read_text(encoding="utf-8")
        _violations = _impl_plan_check.impl_plan_violations(_impl_plan_text)
        if _violations:
            return False, f"impl-plan.md: {_violations[0]}"
        _api_refs = _plan_quality.unresolved_api_refs(_impl_plan_text)
        if _api_refs:
            return False, f"impl-plan.md: {_api_refs[0]}"

    return True, ""


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
