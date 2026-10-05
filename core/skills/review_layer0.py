#!/usr/bin/env python3
"""review_layer0.py — layer 0 of a review run (KLC-175 AC-2).

Layer 0 is the part of a review that needs no model: five deterministic checks
(ac_test_coverage, tdd_order, drift_check, scope_delta, scan_sentinels). Each
runs through its own adapter, and each failing result becomes a `Finding` of
kind `layer0`. The findings go into the ticket's one `findings.json`
(findings_store.write_kind), so the pool, the brief and the report read them
like any other kind.

Two choices worth knowing about:
- A layer-0 finding never blocks by itself. The existing gates (ack, integrate)
  keep deciding; layer 0 only makes their verdict visible to the reviewers.
  It is not a review pass either: `layer0` is not in findings.REVIEW_KINDS.
- An adapter that raises is not silent. It becomes ONE `layer0-unavailable`
  INFO finding that names the check, so a broken check can be told apart from a
  clean one.

Severity: a blocking gate verdict is HIGH, an advisory is MEDIUM or LOW as the
check reports it, an unavailable check is INFO.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

_here = Path(__file__).resolve().parent
for _p in (str(_here), str(_here.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import findings  # noqa: E402
import findings_store  # noqa: E402
from findings import Finding  # noqa: E402

KIND = "layer0"
UNAVAILABLE = "layer0-unavailable"


def _mk(rule: str, severity: str, file: str, line, title: str, body: str,
        fix=None, ref: str = "", ac: str = "") -> Finding:
    return Finding(rule_name=rule, severity=severity, file=file or "-", line=line,
                   title=title, body=body, fix=fix, reviewer=KIND, kind=KIND,
                   ref=ref, ac=ac)


def _unavailable(name: str, why: str) -> Finding:
    return _mk(UNAVAILABLE, "INFO", "-", None, f"layer 0 check {name} unavailable",
               why or "no reason given")


def _track(ticket: str) -> str:
    import ac_test_coverage
    return str(ac_test_coverage._read_meta_ro(ticket).get("track") or "")


def _check_ac_test_coverage(ticket: str, diff_path: Path) -> list[Finding]:
    import ac_test_coverage as atc
    rep = atc.check(ticket, _track(ticket), run_tests=False)   # static only: layer 0 spawns no pytest
    out: list[Finding] = []
    for f in rep.findings:
        if f.state == "covered":
            continue
        if f.state == "degraded":
            out.append(_unavailable("ac_test_coverage", f.message))
            continue
        sev = "HIGH" if f.severity == atc.BLOCK else ("MEDIUM" if f.state == "miss" else "LOW")
        out.append(_mk("ac-test-coverage", sev, "test-plan.md", None,
                       f"{f.ac_id} test coverage: {f.state}", f.message,
                       fix="implement or strengthen the test that proves this AC",
                       ref=f.ac_id, ac=f.ac_id))
    return out


def _check_tdd_order(ticket: str, diff_path: Path) -> list[Finding]:
    import tdd_order
    from _paths import klc_ticket_dir
    from impl_plan_check import parse_impl_plan_steps
    plan = Path(klc_ticket_dir(ticket)) / "impl-plan.md"
    if not plan.is_file():
        raise FileNotFoundError("impl-plan.md not found")
    out: list[Finding] = []
    for s in parse_impl_plan_steps(plan.read_text(encoding="utf-8")):
        n = int(s["id"].split("-")[1])
        if not tdd_order.step_commits(ticket, n):
            continue                                   # a step with no commit is drift_check's finding
        ok, reason = tdd_order.verify_step(ticket, n)
        if not ok:
            out.append(_mk("tdd-order", "HIGH", "impl-plan.md", None,
                           f"{s['id']} breaks red-before-green order", reason,
                           fix="commit the failing test before the implementation",
                           ref=s["id"]))
    return out


def _check_drift_check(ticket: str, diff_path: Path) -> list[Finding]:
    import drift_check
    rep = drift_check.compare(ticket)
    out: list[Finding] = []
    sd = rep.get("scope_drift") or {}
    st = rep.get("step_without_commit") or {}
    if sd.get("skipped"):
        out.append(_unavailable("drift_check", f"scope drift skipped: {sd['skipped']}"))
    for m in sd.get("drifted_modules") or []:
        out.append(_mk("drift-check", "MEDIUM", "-", None, f"module {m} drifted from the plan",
                       f"module {m} changed but is not in the ticket's planned scope",
                       fix="add it to affected_modules or revert the change", ref=str(m)))
    for f in sd.get("orphan_files") or []:
        out.append(_mk("drift-check", "MEDIUM", str(f), None, f"{f} belongs to no module",
                       f"{f} changed and resolves to no known module", ref=str(f)))
    if st.get("skipped"):
        out.append(_unavailable("drift_check", f"step commits skipped: {st['skipped']}"))
    for sid in st.get("flagged") or []:
        out.append(_mk("drift-check", "MEDIUM", "impl-plan.md", None,
                       f"{sid} has no commit", f"no commit names {ticket} {sid}", ref=str(sid)))
    return out


def _check_scope_delta(ticket: str, diff_path: Path) -> list[Finding]:
    import scope_delta
    rep = scope_delta.compare(ticket)
    skipped = rep.get("skipped")
    if skipped:
        if skipped == "no changed files detected":
            return []                                  # nothing changed: nothing to report
        return [_unavailable("scope_delta", str(skipped))]
    out: list[Finding] = []
    expansion = set(rep.get("expansion") or [])
    for m in rep.get("drift") or []:
        blocking = m in expansion                      # an expansion hard-fails the ack today
        out.append(_mk("scope-delta", "HIGH" if blocking else "MEDIUM", "-", None,
                       f"{m} is outside the planned scope",
                       f"{m} changed but is not in meta.affected_modules",
                       fix="add it to affected_modules (ack scope expansion) or drop the change",
                       ref=str(m)))
    return out


def _check_sentinels(ticket: str, diff_path: Path) -> list[Finding]:
    import scan_sentinels
    res = scan_sentinels.scan_diff(Path(diff_path), scan_sentinels.load_sentinels_config())
    out: list[Finding] = []
    for m in res.get("matches") or []:
        sev = str(m.get("severity_override") or "CRITICAL").upper()
        if sev not in findings.SEVERITIES:
            sev = "HIGH"
        text = str(m.get("matched_text") or "")[:80]
        out.append(_mk("sentinel-hit", sev, str(m.get("file") or "-"), m.get("line"),
                       f"sentinel {m.get('sentinel_id', '?')} matched",
                       f"the diff matches sentinel {m.get('sentinel_id', '?')}: {text}",
                       ref=str(m.get("sentinel_id") or "")))
    return out


_CHECKS: list[tuple[str, Callable[[str, Path], list[Finding]]]] = [
    ("ac_test_coverage", _check_ac_test_coverage),
    ("tdd_order", _check_tdd_order),
    ("drift_check", _check_drift_check),
    ("scope_delta", _check_scope_delta),
    ("sentinels", _check_sentinels),
]


def collect(ticket: str, diff_path) -> list[Finding]:
    """Run the five checks; a raising check becomes one degraded finding."""
    out: list[Finding] = []
    for name, check in _CHECKS:
        try:
            out.extend(check(ticket, Path(diff_path)))
        except (Exception, SystemExit) as exc:  # noqa: BLE001 — fail visible, never silent
            # SystemExit too: a check helper that calls sys.exit (a missing
            # config/sentinels.yml does) must not end the whole review.
            out.append(_unavailable(name, f"{type(exc).__name__}: {exc}"))
    return out


def run(ticket: str, diff_path, *, round: int = 1) -> list[Finding]:
    """Run layer 0 for *ticket* over *diff_path* and write the result as the
    `layer0` group of *round* in the ticket's findings.json (replacing that
    group). Returns the findings (ids stamped `L0-001`...). A store that cannot
    be written does not hide the findings: they are still returned."""
    out = collect(ticket, diff_path)
    out = [Finding.from_dict({**f.to_dict(), "id": f"L0-{i:03d}", "round": round})
           for i, f in enumerate(out, start=1)]
    try:
        from _paths import klc_ticket_dir
        tdir = Path(klc_ticket_dir(ticket))
        if tdir.is_dir():
            findings_store.write_kind(tdir, KIND, round, out)
    except OSError as exc:
        sys.stderr.write(f"review_layer0: findings not stored ({exc})\n")
    return out
