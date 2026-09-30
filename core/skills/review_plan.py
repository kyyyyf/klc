#!/usr/bin/env python3
"""review_plan.py — KLC-120: the model-free review-pass planning policy.

Owns everything that is POLICY, not discovery: the external reviewer's
route and gate (step-2), the plan document, the cap and the in-client
`record` command (later steps). `scripts/review.py` keeps its existing
reviewer discovery (manifest, conditional triggers, cascade) and hands
the results here before writing a single job card (design/options.md
Option A, D-006).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import sys
from pathlib import Path


KEYED_PROVIDERS = ("openai", "google")
_TRACK_ORDER = {"XS": 0, "S": 1, "M": 2, "L": 3}

# KLC-120 AC-1: the five sources a pass entry can carry.
SOURCES = ("manifest-always", "manifest-conditional", "cascade-cheap",
          "external", "independent")

# D-005: the operator ruling on spec-review decision D-1 — the manifest's
# four `reviewers.always` entries are always LISTED, never omitted, with
# this reason whenever the in-client path doesn't dispatch them.
PROFILE_SKIP = ("manual workflow does not dispatch profile reviewers "
               "(see KLC-127 Group B)")

# The reason a headless-path pass entry carries for the two passes that
# exist only on the in-client path (code-review, drift).
CLIENT_ONLY = "in-client pass; scripts/review.py does not dispatch it"


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_model(phase_id: str, track: str | None) -> tuple[str, str, str | None]:
    """(provider, model, api_key_env) for *phase_id* on *track*, resolved
    through config/models.yml. Degrades to ("unknown", "unknown", None) on
    any load error (C-004/C-007) — the caller plans the pass anyway rather
    than treating "unknown" as "no risk"."""
    try:
        import models
        r = models.load_models().resolve(phase_id, track=track)
        return r.provider, r.model, r.api_key_env
    except Exception:
        return "unknown", "unknown", None


def external_route(ext_cfg: dict, track: str | None) -> dict:
    """Where the external reviewer's model comes from (KLC-120 D-009).

    A legacy explicit `provider`/`model` block in *ext_cfg* wins — this
    keeps a hand-edited override working. Otherwise the model resolves
    through `config/models.yml`'s `review-external` pseudo-phase (or
    whatever `model_ref` names)."""
    if ext_cfg.get("provider"):
        return {
            "provider": ext_cfg["provider"],
            "model": ext_cfg.get("model", "unknown"),
            "api_key_env": ext_cfg.get("api_key_env"),
            "source": "reviewers.yml",
            "note": None,
        }
    phase = ext_cfg.get("model_ref") or "review-external"
    provider, model, key_env = resolve_model(phase, track)
    note = (None if provider != "unknown"
            else f"models.yml unreadable for {phase}; external planned anyway")
    return {
        "provider": provider,
        "model": model,
        "api_key_env": key_env,
        "source": "models.yml",
        "note": note,
    }


def external_gate(*, no_external: bool, ext_cfg: dict, meta: dict,
                  route: dict | None = None) -> tuple[bool, str | None]:
    """Should the external review pass run? Returns (run, skip_reason).

    The earlier gates (--no-external, meta.review.skip_external, enabled,
    min_track) are unchanged and come first. The last gate decides by
    resolved provider (KLC-120 D-009/F-027): a key-presence check for
    `openai`/`google`, a `claude`-CLI-on-PATH check for `anthropic` — never
    a key check on a route that reads no key."""
    if no_external:
        return False, "--no-external flag"
    if (meta.get("review") or {}).get("skip_external"):
        return False, "meta.review.skip_external"
    if not ext_cfg.get("enabled"):
        return False, "external_reviewer.enabled is false"
    track = meta.get("track", "XS")
    min_track = ext_cfg.get("min_track", "S")
    if _TRACK_ORDER.get(track, 0) < _TRACK_ORDER.get(min_track, 1):
        return False, f"track {track} below min_track {min_track}"
    route = route or external_route(ext_cfg, track)
    provider = route.get("provider")
    if provider in KEYED_PROVIDERS:
        key_env = route.get("api_key_env")
        if key_env and not os.environ.get(key_env):
            return False, f"${key_env} not set"
    elif provider == "anthropic":
        if not shutil.which(os.environ.get("CLAUDE_CLI", "claude")):
            return False, "claude CLI not on PATH"
    return True, None


# --- the plan document (KLC-120 AC-1/AC-2/AC-9) ------------------------------

def pass_entry(reviewer: str, source: str, selected_by: str,
              provider: str | None, model: str | None, status: str,
              skip_reason: str | None = None) -> dict:
    """One `passes[]` entry of `review-plan.json`. `skip_reason` is added
    only when `status == "skipped"` (never a null placeholder on a
    planned/executed entry)."""
    entry = {"reviewer": reviewer, "source": source, "selected_by": selected_by,
             "provider": provider, "model": model, "status": status}
    if status == "skipped":
        entry["skip_reason"] = skip_reason or "unspecified"
    return entry


def mark_executed(plan: dict, reviewers) -> dict:
    """KLC-120 D-015: flip every `planned` pass whose reviewer name is in
    *reviewers* to `executed`. A `skipped` pass never flips — this is how
    the executed count in the report stays equal to the number of
    reviewer-tagged attempts AC-3 writes."""
    names = set(reviewers)
    for p in plan["passes"]:
        if p["reviewer"] in names and p["status"] == "planned":
            p["status"] = "executed"
    return plan


def counted(plan: dict) -> int:
    """The number of passes that count toward the cap — planned or
    executed. Skipped passes never count (D-005)."""
    return sum(1 for p in plan["passes"] if p["status"] in ("planned", "executed"))


def cap_for(track: str | None, reviewers_cfg: dict) -> int | None:
    """`review.max_llm_passes.<track>`, or None when the key (or the track
    inside it) is absent — a missing key means "no cap" (interface-contract
    assumption), never cap-zero."""
    caps = ((reviewers_cfg or {}).get("review") or {}).get("max_llm_passes") or {}
    value = caps.get(track) if isinstance(caps, dict) else None
    return int(value) if isinstance(value, int) else None


def load_reviewers_cfg() -> tuple[dict, str | None]:
    """Read config/reviewers.yml, degrading to ({}, a note) on any error
    (C-004/C-007) rather than raising — the caller plans every pass
    anyway."""
    try:
        from _paths import framework_root
        from _yaml import parse as _yml_parse
        path = framework_root() / "config" / "reviewers.yml"
        if not path.exists():
            return {}, "config/reviewers.yml not found; no cap, external route unknown"
        return _yml_parse(path.read_text(encoding="utf-8")) or {}, None
    except Exception as exc:
        return {}, f"config/reviewers.yml unreadable ({exc}); no cap, external route unknown"


def build_plan(*, ticket: str | None, track: str | None, path: str,
               diff_sha256: str, cap: int | None, override: bool,
               passes: list, cascade: dict | None = None,
               notes: tuple | list = ()) -> dict:
    """The whole `review-plan.json` document. `per_step_build_review` is a
    fixed field (Q-006) — per-step build review is out of this ticket's
    inventory, stated once rather than silently omitted."""
    return {
        "ticket": ticket,
        "track": track,
        "path": path,
        "generated_at": _utc_now(),
        "diff_sha256": diff_sha256,
        "cap": cap,
        "override": bool(override),
        "per_step_build_review": "not counted",
        "cascade": cascade,
        "notes": list(notes),
        "passes": list(passes),
    }


def carry_forward(new_plan: dict, old_plan: dict | None) -> dict:
    """AC-29: keep `executed` across a re-plan of the SAME diff only.

    `scripts/review.py --plan-only` re-run for a ticket whose diff hasn't
    changed must never reset an already-`executed` pass back to `planned` —
    that would let `handback.py take`'s step-0 planner call (KLC-127 AC-8)
    record the same pass twice. A different diff (or an unreadable/garbled
    *old_plan*) is simply ignored: *new_plan* is returned untouched, so a
    genuinely new run plans fresh. A pass the new plan now marks `skipped`
    is never revived to `executed` — only a `planned` entry is flipped.
    """
    if not isinstance(old_plan, dict) or old_plan.get("diff_sha256") != new_plan.get("diff_sha256"):
        return new_plan
    done = {p.get("reviewer") for p in old_plan.get("passes") or []
            if p.get("status") == "executed"}
    for p in new_plan["passes"]:
        if p["reviewer"] in done and p["status"] == "planned":
            p["status"] = "executed"
    if done and old_plan.get("generated_at"):
        new_plan["generated_at"] = old_plan["generated_at"]   # same record_pass attempt id
    return new_plan


def write_plan(ticket: str, plan: dict) -> Path | None:
    """Atomic write of `.klc/tickets/<KEY>/review-plan.json` — the latest
    run wins. A write failure degrades to one stderr note, never a failed
    review (C-007)."""
    try:
        from _paths import klc_ticket_dir
        out = klc_ticket_dir(ticket) / "review-plan.json"
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        tmp.replace(out)
        return out
    except OSError as exc:
        sys.stderr.write(f"review-plan: not written ({exc})\n")
        return None


def plan_lines(plan: dict) -> list[str]:
    """Human-readable summary lines for the CLI log (spec's Operator flow
    example)."""
    planned = [p for p in plan["passes"] if p["status"] in ("planned", "executed")]
    skipped = [p for p in plan["passes"] if p["status"] == "skipped"]
    names = ", ".join(p["reviewer"] for p in planned) or "none"
    lines = [f"review plan: {len(planned)} passes ({names})"]
    if skipped:
        lines.append("skipped: " + "; ".join(
            f"{p['reviewer']} ({p.get('skip_reason', 'unspecified')})"
            for p in skipped))
    lines.append(f"per-step build review: {plan['per_step_build_review']}")
    return lines


# --- the in-client `record` command (KLC-120 AC-3/AC-11) --------------------

class RecordRefused(Exception):
    """review-fix HIGH (AC-3/AC-4): `record_pass` refuses rather than
    trusting the caller — raised when review-plan.json is missing, the
    named reviewer isn't one of its passes, or that pass is `skipped`."""


def _plan_attempt_id(ticket: str, plan: dict, reviewer: str) -> str:
    import hashlib
    seed = f"{ticket}|{plan.get('generated_at')}|{plan.get('diff_sha256')}|{reviewer}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def record_pass(ticket: str, reviewer: str, *, phase: str = "review",
                output: Path | None = None) -> str:
    """Record one reviewer-tagged attempt for an in-client executed pass,
    through the one writer (C-008), and flip that pass to `executed` in
    the ticket's review-plan.json.

    review-fix HIGH (AC-3/AC-4): the plan is read FIRST and is the sole
    authority on whether *reviewer* may be recorded — this is not
    optional bookkeeping, it is what keeps `review_llm_passes_per_ticket`
    honest. Raises `RecordRefused` (never writes an attempt) when:
      - no review-plan.json exists for *ticket*;
      - *reviewer* is not one of the plan's `passes[]`;
      - that pass's status is `skipped` (it was never meant to run).
    A repeated call for a pass whose status is already `executed` is a
    documented no-op success (D-120-10): it returns the same
    deterministic attempt id without writing a second attempt or
    rewriting the plan, keeping today's idempotence on a retried
    `record` for the same pass of the same run.

    The attempt id is derived from the plan's `generated_at`,
    `diff_sha256` and *reviewer*, so a repeated call for the same run
    collapses to one attempt in `metrics.iter_attempts`."""
    import budget_guard
    from _paths import klc_ticket_dir
    plan_file = klc_ticket_dir(ticket) / "review-plan.json"
    if not plan_file.is_file():
        raise RecordRefused(
            f"no review-plan.json for {ticket} — run the planner "
            "(--plan-only) before recording a pass")
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordRefused(f"review-plan.json for {ticket} is unreadable: {exc}")

    entry = next((p for p in (plan.get("passes") or [])
                 if p.get("reviewer") == reviewer), None)
    if entry is None:
        raise RecordRefused(
            f"{reviewer!r} is not a pass in {ticket}'s review-plan.json")
    if entry.get("status") == "skipped":
        raise RecordRefused(
            f"{reviewer!r} is skipped in {ticket}'s review-plan.json "
            f"({entry.get('skip_reason', 'unspecified')}) — it was never "
            "planned to run")

    attempt_id = _plan_attempt_id(ticket, plan, reviewer)
    if entry.get("status") == "executed":
        # D-120-10: no-op success — already recorded for this run, return
        # the same id without a second write or plan rewrite.
        return attempt_id

    out_tokens = 0
    if output is not None:
        out_path = Path(output)
        if out_path.is_file():
            out_tokens = budget_guard.estimate_tokens(
                out_path.read_text(encoding="utf-8", errors="ignore"))
    budget_guard.write_token_metrics(
        ticket, phase, 0, out_tokens, 0, source="estimated",
        attempt_id=attempt_id, reviewer=reviewer)
    mark_executed(plan, [reviewer])
    write_plan(ticket, plan)
    return attempt_id


def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="review_plan", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_rec = sub.add_parser("record", help="record one executed review pass")
    p_rec.add_argument("--ticket", required=True)
    p_rec.add_argument("--reviewer", required=True)
    p_rec.add_argument("--phase", default="review")
    p_rec.add_argument("--output", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.cmd == "record":
        try:
            attempt_id = record_pass(args.ticket, args.reviewer, phase=args.phase,
                                     output=args.output)
        except RecordRefused as exc:
            sys.stderr.write(f"review_plan record: {exc}\n")
            return 2
        print(attempt_id)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
