"""step_ledger.py — KLC-114: the post-build step ledger pass.

A mechanical second opinion the orchestrator computes from git and from
re-executed commands, instead of trusting the builder's own report. See
`.klc/tickets/KLC-114/spec.md` for the full rationale.

`judge_step(ticket, step, repo=None, *, deadline=None, budget_s=None)`
re-executes one impl-plan step's `VERIFY:` command through
`verify_runner.run` and requires the step's isolated `Expected:` outcome
token (`step_verify.expected_token`) to appear in the captured output
(AC-4). It reuses `step_verify._clean_command`/`_is_placeholder` for
command cleaning and `verify_runner` for opaque, language-agnostic
execution (C-003) — no test-framework name appears anywhere in this
module's own logic (AC-13).
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

import build_ledger  # noqa: E402
import impl_plan_check  # noqa: E402
import settings  # noqa: E402
import step_verify  # noqa: E402
import tdd_order  # noqa: E402
import test_conventions  # noqa: E402
import verify_runner  # noqa: E402
from _paths import klc_ticket_dir, project_root  # noqa: E402

GREEN, RED, UNVERIFIED, SCOPE_VIOLATION = "green", "red", "unverified", "scope-violation"


@dataclass(frozen=True)
class StepVerdict:
    step_id: str
    state: str
    reason: str = ""
    command: str = ""
    output: str = ""
    ac_ids: tuple = ()


def _one_line(reason: str) -> str:
    """Collapse a possibly multi-line reason to one line for the journal."""
    return " ".join((reason or "").split())


def _repo_root(repo) -> Path:
    return Path(repo) if repo is not None else project_root()


def _touched_paths(commits: list[dict], repo=None) -> list[str]:
    """The ordered, de-duplicated union of every path touched by *commits*
    (oldest-first, matching `tdd_order.step_commits`'s own order)."""
    seen: list[str] = []
    for c in commits:
        out = tdd_order._git(["show", "--name-only", "--format=", c["sha"]], repo)
        for line in out.splitlines():
            p = line.strip()
            if p and p not in seen:
                seen.append(p)
    return seen


def _out_of_scope(paths: list[str], declared: list[str]) -> list[str]:
    """The subset of *paths* outside the declared `Affected:` surface,
    widened by two policy exceptions: any path carrying a recognised
    test-directory segment (D-114-10, supersedes D-114-8:
    `test_conventions.in_test_directory` — a TDD step must be free to add
    its own test file) and, when the step already declares a `core/agents`
    source edit, any `klc-plugin/` path (C-006 makes that regeneration
    mandatory).

    D-114-10 (review round 1, MEDIUM; AC-2/AC-13): `is_test_path`/
    `test_signal` also promote a "sibling: none" basename convention
    (`conftest.py`, `tests.rs`, `test.rs`, ...) to a test UNCONDITIONALLY,
    even OUTSIDE any declared test directory — broader than AC-2/AC-13's
    literal "has no tests path segment" wording, so a bare `conftest.py`
    dropped outside `tests/` would have been silently exempted from scope
    checking. `in_test_directory` is the directory-signal-ONLY predicate
    that closes this gap; it needs no `exists=` opt-in at all (KLC-109's
    `test_every_consumer_call_passes_exists` guard only scans calls to
    `is_test_path`/`test_signal` by name, not this one)."""
    plugin_ok = any(d.lstrip("`").startswith("core/agents") for d in declared)
    stray = []
    for p in paths:
        if test_conventions.in_test_directory(p):
            continue
        if impl_plan_check.affected_allows(p, declared):
            continue
        if plugin_ok and p.startswith("klc-plugin/"):
            continue
        stray.append(p)
    return stray


def _plan_steps(ticket: str) -> list[dict]:
    """Every parsed `## step-N` block for *ticket*, or `[]` when
    impl-plan.md is absent or parses to zero steps."""
    plan_path = klc_ticket_dir(ticket) / "impl-plan.md"
    if not plan_path.exists():
        return []
    return impl_plan_check.parse_impl_plan_steps(plan_path.read_text(encoding="utf-8"))


def _plan_step(ticket: str, step: int) -> dict | None:
    """Return the parsed `## step-N` block for *step*, or None when
    impl-plan.md is absent or does not declare that step."""
    target = f"step-{step}"
    for s in _plan_steps(ticket):
        if s["id"] == target:
            return s
    return None


def _num(step_id: str) -> int:
    m = re.search(r"\d+", step_id)
    return int(m.group()) if m else 0


def judge_step(ticket: str, step: int, repo=None, *,
               deadline: float | None = None, budget_s: float | None = None,
               cache: dict | None = None) -> StepVerdict:
    """Judge one impl-plan step `green`, `red` or `unverified` from a
    re-executed `VERIFY:` command plus the isolated `Expected:` token.

    *cache* (KLC-114 review round 1, HIGH; AC-1/AC-11/C-005): an optional
    per-ack Verdict cache, keyed by `(ticket, step_id, command)`, SHARED
    with `step_verify.check_steps` so the same step's same VERIFY command
    executes at most once per `can_complete_build` call — not once per
    arm. `None` (the default) disables caching, unchanged for every other
    caller (`run_build`'s per-step judge, a standalone/test call, ...)."""
    sid = f"step-{step}"
    plan_step = _plan_step(ticket, step)
    if plan_step is None:
        return StepVerdict(sid, UNVERIFIED, "no-plan-step")

    fields = impl_plan_check.extract_step_fields(plan_step["body"])
    acs = tuple(plan_step["addresses"])
    command = step_verify._clean_command(fields.get("verify", ""))
    token = step_verify.expected_token(fields.get("expected", ""))

    if step_verify._is_placeholder(command):
        return StepVerdict(sid, UNVERIFIED, "verify-placeholder", command, "", acs)
    if not token:
        return StepVerdict(sid, UNVERIFIED, "expected-unmatchable", command, "", acs)

    commits = tdd_order.step_commits(ticket, step, repo)
    if not commits:                       # Q-002: absence of evidence, never RED
        return StepVerdict(sid, UNVERIFIED, "no-commits", command, "", acs)

    ok, order_reason = tdd_order.verify_step(ticket, step, repo)
    stray = _out_of_scope(_touched_paths(commits, repo), fields.get("affected", []))
    # precedence: RED beats SCOPE_VIOLATION beats UNVERIFIED beats GREEN (D-014)
    if not ok:
        reason = order_reason if not stray else (
            f"{order_reason}; also outside the declared surface: {stray[0]}")
        return StepVerdict(sid, RED, _one_line(reason), command, "", acs)
    if stray:
        return StepVerdict(sid, SCOPE_VIOLATION,
                           f"{stray[0]} outside the declared surface of {sid}",
                           command, "", acs)

    if deadline is None:
        deadline = time.monotonic() + settings.verify_arm_budget()
    if time.monotonic() >= deadline:
        return StepVerdict(sid, UNVERIFIED, "arm-budget-exhausted", command, "", acs)

    v = verify_runner.run_cached(cache, (ticket, sid, command), command,
                                 budget_s=budget_s or settings.verify_step_budget(),
                                 cwd=str(_repo_root(repo)))
    if v.state == verify_runner.UNVERIFIED:
        return StepVerdict(sid, UNVERIFIED, f"{v.reason}: {v.detail}", command, v.output, acs)
    if v.state == verify_runner.FAILED:
        return StepVerdict(sid, RED, f"VERIFY exited {v.exit_code}", command, v.output, acs)
    if not step_verify._token_in_output(token, v.output):
        return StepVerdict(sid, RED, f"expected token {token!r} not found in the VERIFY output",
                           command, v.output, acs)
    return StepVerdict(sid, GREEN, "", command, v.output, acs)


@dataclass
class LedgerReport:
    ticket: str
    verdicts: list = field(default_factory=list)
    note: str = ""
    wrote: bool = False

    def canonical(self) -> str:
        """Timestamp-free projection — the byte-identity surface for AC-1."""
        return "\n".join(f"{v.step_id}\t{v.state}\t{v.reason}" for v in self.verdicts) + "\n"


def verify_build_steps(ticket: str, repo=None, *, write: bool = True,
                       deadline: float | None = None, cache: dict | None = None) -> LedgerReport:
    """Walk every impl-plan step, judge it, and (when *write*) persist the
    verdicts to `build/progress.md`. Degrades to a stated `note` instead of
    raising when impl-plan.md is absent or parses to zero steps (AC-6).

    *cache*: threaded straight through to `judge_step` — see its own
    docstring (KLC-114 review round 1, HIGH)."""
    steps = _plan_steps(ticket)
    if not steps:
        return LedgerReport(ticket, [], note="impl-plan.md is absent or parses to zero steps")

    verdicts = [judge_step(ticket, _num(s["id"]), repo, deadline=deadline, cache=cache)
               for s in steps]
    if not write:
        return LedgerReport(ticket, verdicts, note="read-only")

    led = build_ledger.Ledger.load(ticket) or build_ledger.Ledger.from_plan(ticket)
    for v in verdicts:                       # D-009: every step, every run
        led.mark(v.step_id, v.state, reason=_one_line(v.reason) or None)
    led.save()
    _write_evidence(ticket, verdicts)
    return LedgerReport(ticket, verdicts, wrote=True)


# --- machine-made Evidence rows (AC-7) ---------------------------------------

_EVID_BEGIN, _EVID_END = "<!-- klc-ledger:begin -->", "<!-- klc-ledger:end -->"

# D-114-11 (CRITICAL, step-11): a re-executed VERIFY's stdout is UNTRUSTED
# input to this module — an external reviewer reproduced a forgery where a
# VERIFY that prints a closing fence, then a paragraph-initial `AC-<n>`
# line, then a NEW fenced `$ cmd` block, made `evidence_gate.parse_evidence`
# read a well-formed `pass` entry for an AC the step never addressed,
# silently defeating the M/L no-entry block. The fix is structural, not a
# blocklist: the machine row NEVER embeds the raw, multi-line, verbatim
# command/output again. Every backtick is stripped (the only character
# that can open/close a markdown fence) and every `AC-<n>` token is
# neutralised (the only anchor `parse_evidence` recognises), so no
# sanitised summary line can ever forge a fence boundary or a new anchor,
# regardless of what the re-executed command prints.
_MAX_EVID_COMMAND_CHARS = 200
_MAX_EVID_OUTPUT_CHARS = 120
_AC_TOKEN_RE = re.compile(r"(?i)AC-(?=\d)")


def _sanitize_for_fence(s: str) -> str:
    """Collapse *s* to ONE line and strip every backtick, `AC-<n>` token,
    and HTML-comment delimiter — see the D-114-11 module note above, and
    D-114-15 (review round 2, HIGH): the module's OWN
    `<!-- klc-ledger:begin/end -->` span markers are a second injection
    surface `_sanitize_for_fence` originally left open — a VERIFY whose
    command or output carries one of these literal strings would survive
    into the rendered fence and let `_splice_evidence`'s span regex match
    a FAKE marker instead of the real one. Never used to carry verbatim,
    multi-line, attacker-influenced text into a fence again."""
    s = " ".join((s or "").split())
    s = s.replace("`", "'")
    s = s.replace("<!--", "<!-").replace("-->", "->")
    return _AC_TOKEN_RE.sub("AC_", s)


def _evidence_summary_lines(v: StepVerdict) -> tuple[str, str]:
    """(command_line, output_line): a BOUNDED, single-line, sanitised
    summary of the re-executed VERIFY — never the raw command/output
    verbatim (D-114-11). `parse_evidence` still sees a well-formed entry
    (one `$ ...` command line plus one non-command output line), but every
    character that could open a fence or an anchor has been removed."""
    cmd = _sanitize_for_fence(v.command)[:_MAX_EVID_COMMAND_CHARS]
    out = (v.output or "").strip()
    last_line = out.splitlines()[-1] if out else "(no output captured)"
    summary = _sanitize_for_fence(last_line)[:_MAX_EVID_OUTPUT_CHARS]
    return f"$ {cmd}", f"VERIFY passed; last output line: {summary}"


def _render_evidence_block(verdicts: list[StepVerdict]) -> str:
    """One entry per AC id of every GREEN step, in the shape
    `evidence_gate.parse_evidence` already accepts: a paragraph-initial
    line naming the AC id, then a fenced `$ command` line plus a bounded,
    sanitised output summary (D-005: only an earned pass is ever claimed
    here; D-114-11: never the raw command/output verbatim)."""
    rows = []
    for v in verdicts:
        if v.state != GREEN:
            continue
        cmd_line, out_line = _evidence_summary_lines(v)
        for ac in v.ac_ids:
            rows.append(
                f"\n{ac} — {v.step_id} VERIFY re-run by the step ledger pass (source: ledger)\n"
                f"\n```text\n{cmd_line}\n{out_line}\n```\n")
    return "" if not rows else _EVID_BEGIN + "\n" + "".join(rows) + "\n" + _EVID_END + "\n"


_EVID_SPAN_RE = re.compile(
    r"^" + re.escape(_EVID_BEGIN) + r"[ \t]*$.*?^" + re.escape(_EVID_END) + r"[ \t]*$\n?",
    re.DOTALL | re.MULTILINE)


def _splice_evidence(text: str, block: str) -> str:
    """Cut any existing machine span, then splice *block* in at the end of
    the FIRST `## Evidence` section (F-101) — adding that heading only when
    the file has none. The builder's own entries, before or after the spliced
    block, are never touched.

    D-114-15 (review round 2, HIGH): the span markers are matched ONLY as
    WHOLE LINES (`^...$` under `re.MULTILINE`), never as a bare substring
    anywhere in the text — a marker-shaped string embedded inside a
    rendered command/output line (which always carries other text around
    it, e.g. `$ ...` or `VERIFY passed; ...`) can therefore never satisfy
    a whole-line match and can never terminate the span early, even if
    `_sanitize_for_fence` were ever bypassed."""
    text = _EVID_SPAN_RE.sub("", text)
    m = re.search(r"^## Evidence\b", text, re.MULTILINE)
    if not m:
        return text.rstrip("\n") + "\n\n## Evidence\n\n" + block
    nxt = re.search(r"^## ", text[m.end():], re.MULTILINE)
    cut = m.end() + (nxt.start() if nxt else len(text) - m.end())
    return text[:cut].rstrip("\n") + "\n\n" + block + "\n" + text[cut:]


def _write_evidence(ticket: str, verdicts: list[StepVerdict]) -> None:
    """Splice the machine Evidence block into build-log.md. A no-op (never
    raises) when there is nothing to claim, or build-log.md does not exist —
    the boundary assumption is degrade-and-write-nothing, not fabricate a
    file the builder never wrote."""
    block = _render_evidence_block(verdicts)
    if not block:
        return
    log_path = klc_ticket_dir(ticket) / "build-log.md"
    if not log_path.exists():
        return
    text = log_path.read_text(encoding="utf-8")
    log_path.write_text(_splice_evidence(text, block), encoding="utf-8")


def advisory_records(report: LedgerReport) -> list[dict]:
    """The record form the aggregator's one advisory stream expects
    (KLC-117 shape). Q-004: `red`/`scope-violation` verdicts surface as
    `high`-severity advisories — never a new hard breach; `unverified`
    surfaces at `medium` (an inability to observe, not a definite negative,
    D-204); `green` produces no record at all."""
    records = []
    for v in report.verdicts:
        if v.state in (RED, SCOPE_VIOLATION):
            severity = "high"
        elif v.state == UNVERIFIED:
            severity = "medium"
        else:
            continue
        records.append({
            "source": "ledger", "severity": severity,
            "code": f"ledger.{v.state}",
            "message": f"{v.step_id}: {v.state} — {v.reason}" if v.reason else
                      f"{v.step_id}: {v.state}",
            "ref": v.step_id,
        })
    return records


# --- CLI (D-114-7): the third of the three call sites named in this
# ticket's design — `/klc:run`'s post-build sub-step runs this exact
# command (KLC-114 step-9) --------------------------------------------------

def main(argv=None) -> int:
    """`python3 core/skills/step_ledger.py --ticket <KEY>` — re-run every
    impl-plan step's VERIFY, write `build/progress.md` and the machine
    Evidence rows, and print one `step_id  state  reason` line per step."""
    import argparse
    parser = argparse.ArgumentParser(
        description="KLC-114: the post-build step ledger pass")
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--repo", default=None,
                        help="git repository to attribute commits against "
                             "(default: the current working directory)")
    args = parser.parse_args(argv)

    report = verify_build_steps(args.ticket, args.repo, write=True)
    for v in report.verdicts:
        print(f"{v.step_id}\t{v.state}\t{v.reason}")
    if report.note:
        print(report.note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
