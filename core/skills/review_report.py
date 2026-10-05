#!/usr/bin/env python3
"""review_report.py — KLC-175 F-002: render the TICKET's `review-report.md`
without a model.

Both review paths end in `.klc/tickets/<KEY>/review-report.md`: the file the
`publish` verb, the review gate and the retrospective read. The headless path
renders it through `scripts/review.py`'s own template; the in-client path (an
agent that ran the planned passes) calls `scripts/review.py --report`, which
lands here, so the report is never hand-written and never lacks its `## Where
to look` and cost lines.

Everything comes from facts on disk, no model call:
- findings: the latest round of each kind in the ticket's `findings.json`,
  grouped by kind. A finding is BLOCKING when its severity is in
  `review.blocking_severity` (default CRITICAL/HIGH), its kind is not `layer0`
  (layer 0 never blocks by itself) and the assessments do not say it was fixed
  or is won't-fix;
- passes: the latest `review/review-plan-r<N>.json` (planned / executed /
  skipped, inlined bytes, notes, signals);
- duplicate rate: THIS run's raw review findings against their deduped pool,
  not a `findings-pool.json` an earlier round left behind;
- Where to look: `review_map` over the diff.

Assessments (`--assessments <json>`): a list of `{id, kind?, disposition}`;
dispositions `fixed`, `fix`, `wont-fix` (also `won't-fix`, `wontfix`) resolve a
finding. An id without a `kind` matches that id in every kind.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

APPROVED = "APPROVED"
CHANGES_REQUESTED = "CHANGES REQUESTED"
_RESOLVED = {"fixed", "fix", "wont-fix", "won't-fix", "wontfix"}
_WONTFIX = {"wont-fix", "won't-fix", "wontfix"}
_DEFAULT_BLOCKING = ("CRITICAL", "HIGH")
_NON_REVIEW_PASSES = ("code-review", "external", "drift")


def load_assessments(path) -> list[dict]:
    """The assessments file as a list of dicts; raises ValueError on junk."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("assessments", raw.get("findings"))
    if not isinstance(raw, list):
        raise ValueError("assessments must be a JSON list of {id, disposition}")
    return [r for r in raw if isinstance(r, dict)]


def _disposition(row: dict, assessments: list[dict]) -> str:
    for a in assessments:
        if str(a.get("id")) == str(row.get("id")) and a.get("kind") in (None, row.get("kind")):
            return str(a.get("disposition", "")).strip().lower()
    return ""


def _latest(rows: list[dict], tdir: Path) -> list[dict]:
    try:
        import handback
        return handback._latest_rounds(rows, tdir)
    except Exception:  # noqa: BLE001 — degrade to the highest round of each kind
        import findings_store as fs
        top: dict = {}
        for d in rows:
            k = str(d.get("kind") or "")
            top[k] = max(top.get(k, 0), fs._round_of(d))
        return [d for d in rows if fs._round_of(d) == top[str(d.get("kind") or "")]]


def duplicate_rate(tdir: Path, rows: list[dict]) -> str:
    """This run's duplicate rate: the latest round's raw review findings against
    their deduped pool. `n/a` when fewer than two reviewers contributed."""
    try:
        import findings
        items = []
        for d in rows:
            if d.get("kind") in ("code-review", "external-review"):
                items.append(findings.Finding.from_dict(d))
        pool = findings.build_pool(items, ticket=tdir.name,
                                   min_similarity=findings.min_similarity())
        rate = pool.get("duplicate_rate")
    except Exception:  # noqa: BLE001
        return "n/a"
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        return "n/a"
    return f"{rate:.2f}"


def where_to_look(diff_text: str, tdir: Path | None, framework_root: Path,
                  repo_root: Path, file_tiers: dict, assessments=None) -> str:
    """The rendered `## Where to look` section. Never raises."""
    import review_map
    try:
        from _yaml import parse as _yml_parse
        cfg_path = Path(framework_root) / "config" / "reviewers.yml"
        cfg = _yml_parse(cfg_path.read_text()) if cfg_path.exists() else {}
        cfg = {"where_to_look": (cfg or {}).get("where_to_look") or {},
               "repo_root": str(repo_root)}
        return review_map.render(review_map.build(diff_text, tdir, cfg, file_tiers, assessments))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[review] where-to-look unavailable: {exc}\n")
        return review_map.render({})


def _fmt_finding(d: dict) -> str:
    loc = f"{d.get('file', '?')}:{d['line']}" if d.get("line") is not None else str(d.get("file", "?"))
    return (f"- [{d.get('severity', '?')}] {d.get('title', '(no title)')} — {loc} "
            f"({d.get('kind', '?')} {d.get('id', '')})".rstrip())


def render(*, ticket: str, spec_path, tdir: Path, plan: dict | None, rows: list[dict],
           assessments: list[dict], where: str, verdict: str | None,
           blocking_severity=_DEFAULT_BLOCKING, notes=()) -> tuple[str, str]:
    """(report markdown, verdict). *rows* are the latest-round findings."""
    blocking_sev = set(blocking_severity or _DEFAULT_BLOCKING)
    blocking, non_blocking = [], []
    per_kind: dict[str, list[int]] = {}
    for d in rows:
        kind = str(d.get("kind") or "?")
        disp = _disposition(d, assessments)
        is_block = (str(d.get("severity", "")).upper() in blocking_sev
                    and kind != "layer0" and disp not in _RESOLVED)
        (blocking if is_block else non_blocking).append(d)
        cnt = per_kind.setdefault(kind, [0, 0])
        cnt[0] += 1
        cnt[1] += int(is_block)
    final = verdict or (CHANGES_REQUESTED if blocking else APPROVED)
    final = CHANGES_REQUESTED if final.replace("_", " ").upper() == CHANGES_REQUESTED else APPROVED

    plan = plan or {}
    passes = plan.get("passes") or []
    planned = sum(1 for p in passes if p.get("status") in ("planned", "executed"))
    executed = sum(1 for p in passes if p.get("status") == "executed")
    depth = "L1+L2" if any(p.get("status") == "executed"
                           and p.get("reviewer") not in _NON_REVIEW_PASSES for p in passes) else "L1"
    skipped = [p for p in passes if p.get("status") == "skipped"]
    all_notes = list(plan.get("notes") or []) + list(notes)
    sigs = plan.get("signals") or {}
    if sigs.get("unevaluable"):
        all_notes.append("signals unevaluable (their specialists were planned): "
                         + ", ".join(sigs["unevaluable"]))

    head = [
        "# Code Review Report",
        f"Generated: {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"Spec: {spec_path}",
        f"review_depth: {depth}",
        f"planned_passes: {planned if passes else 'n/a'}",
        f"executed_passes: {executed if passes else 'n/a'}",
        f"review_duplicate_rate: {duplicate_rate(tdir, rows)}",
        f"inlined_bytes_in_client: {plan.get('inlined_bytes_in_client', 'n/a')}",
        f"inlined_bytes_headless: {plan.get('inlined_bytes_headless', 'n/a')}",
    ]
    if plan.get("override"):
        head.append("cap_override: true")
        head.append(f"cap: {plan.get('cap')}")
    table = ["", "## Summary", "| Findings of | Issues | Blocking |", "|---|---|---|"]
    table += [f"| {k} | {c[0]} | {c[1]} |" for k, c in sorted(per_kind.items())] \
        or ["| (no findings recorded) | 0 | 0 |"]
    pass_lines = ["", "## Review passes",
                  f"Planned: {planned if passes else 'n/a'} · Executed: "
                  f"{executed if passes else 'n/a'} · per-step build review: not counted"]
    pass_lines += [f"- skipped `{p.get('reviewer')}` — {p.get('skip_reason', 'unspecified')}"
                   for p in skipped]
    pass_lines += [f"- note: {n}" for n in all_notes]
    fmt = lambda ds: "\n".join(_fmt_finding(d) for d in ds) if ds else "_None._"  # noqa: E731
    body = (
        "\n".join(head) + "\n" + "\n".join(table) + "\n\n" + where.strip() + "\n"
        + "\n".join(pass_lines) + "\n\n"
        "## Blocking Issues (must fix before merge)\n" + fmt(blocking) + "\n\n"
        "## Non-blocking Issues (recommended)\n" + fmt(non_blocking) + "\n\n"
        f"---\n## Verdict: {final}\n"
    )
    return body, final


def write(*, ticket: str, spec_path, diff_text: str, file_tiers: dict,
          framework_root: Path, repo_root: Path, verdict: str | None = None,
          assessments_path=None) -> tuple[Path, str]:
    """Render and write `<ticket dir>/review-report.md`; returns (path, verdict)."""
    import findings_store
    import review_plan
    from _paths import klc_ticket_dir
    tdir = Path(klc_ticket_dir(ticket))
    assessments = load_assessments(assessments_path) if assessments_path else []
    all_rows, store_notes = findings_store.read_dicts(tdir)
    rows = _latest(all_rows, tdir)
    by_id = {(r.get("kind"), str(r.get("id"))): r for r in rows}
    map_assess = []
    for a in assessments:                   # join to the finding for file/line/severity
        for (k, i), r in by_id.items():
            if i == str(a.get("id")) and a.get("kind") in (None, k):
                map_assess.append({"file": r.get("file"), "line": r.get("line"),
                                   "severity": r.get("severity"),
                                   "disposition": a.get("disposition")})
    plan_path = review_plan.latest_plan_path(ticket)
    plan = review_plan._plan_doc(plan_path) if plan_path else None
    cfg, _note = review_plan.load_reviewers_cfg()
    text, final = render(
        ticket=ticket, spec_path=spec_path, tdir=tdir, plan=plan, rows=rows,
        assessments=assessments,
        where=where_to_look(diff_text, tdir, framework_root, repo_root, file_tiers, map_assess),
        verdict=verdict,
        blocking_severity=((cfg.get("review") or {}).get("blocking_severity")),
        notes=[n for n in store_notes])
    out = tdir / "review-report.md"
    out.write_text(text, encoding="utf-8")
    return out, final
