---
ticket: KLC-115
phase: design
track: M
kind: tech
authority: agent
option: A
adr: design/adr.md
revision: 2
last_generated: 2026-09-17T12:00:00Z
---

# KLC-115 — implementation plan (revision 2)

Eight steps, each one logical commit. Step 1 lands the shared seam (the bounded
runner and its budgets) so that no later step has to invent a second timeout;
steps 2–5 build the three consuming gates on top of it; steps 6–7 close the FACT
discipline and the arm-level degrade guard; step 8 is the prompt and documentation
contract.

**What changed in revision 2.** The independent impl-plan review returned four
findings. The step skeleton is unchanged — the review confirmed the runner
promotion, the AC-to-step map, the backward-only dependency graph, the
execution-free probe path and the same-commit settings-schema registration — so
each fix lands inside the step that already owns that behaviour, rather than as a
separate commit that would deliberately leave an intermediate state broken.

| Finding | Fix | Decision | Owning step |
|---|---|---|---|
| F-1 | per-node classification reads the pytest outcome token through the parser that already exists, so a skipped node is never a pass | D-201 | step-5 |
| F-2 | the `Expected:` comparison isolates the outcome token, proved against all 25 real `Expected:` fields in KLC-103, KLC-107 and KLC-113 | D-202 | step-4 |
| F-3 | the FACT-source rule blocks only for an opted-in item or a ticket created after a constant epoch, and warns otherwise, so no in-flight ticket breaks and no other ticket is edited | D-203 | step-6 |
| F-4 | an Evidence re-run that exceeded its budget or could not be launched surfaces on every track; only a non-zero exit and a missing entry block | D-204, D-205 | step-3 |

> [!DECISION D-301] owner=impl-agent date=2026-09-17
> Discovered during step-3 planning (not one of F-1..F-4): `tests/test_ac_test_coverage.py`'s
> shared `_make_full_build_ticket` fixture writes a real SAOC spec.md but a
> generic, non-per-AC `## Evidence` block — precisely the AC-18 "pasted prose,
> one unattributed fence" shape this ticket's gate must BLOCK on track M.
> Wiring `evidence_gate` unconditionally into `can_complete_build` would
> independently block four of that file's `can_complete_build` integration
> tests for a reason none of them are about (they exercise `ac_test_coverage`'s
> own block/override/degrade behaviour), and would try to re-execute that
> fixture's generic pytest command for real. Fix: add
> `"deferred_verify_evidence": True` to that one shared fixture's `meta` dict —
> additive, assertion-preserving, no test behaviour changed — rather than
> touching any assertion. This is a scope expansion beyond step-3's own
> `Affected` list (`tests/test_ac_test_coverage.py` is not listed there),
> within the `tests` category the dispatch permits.

**Standing rule for this plan (C-005).** Any step whose `Affected` list contains a
path under `core/agents/` must run `python3 core/skills/plugin_gen.py` and stage
the regenerated `klc-plugin/` files in the same commit. Only step 8 is affected.

**Standing rule on regressions.** Every step keeps
`tests/test_ac_test_coverage.py`, `tests/test_impl_plan_check.py`,
`tests/test_tdd_order.py`, `tests/integration/test_build_evidence_gate.py` and
`tests/integration/test_klc107_refresh.py` green **unmodified**. Step 5 is the
one most likely to disturb the first of those, and D-201 exists precisely so it
does not: `tests/test_ac_test_coverage.py:583`
(`test_verify_passing_skip_is_not_passing`) must still pass against the same
outcome parser it exercises today.

**Standing rule on counts.** Where a step's VERIFY runs a pre-existing regression
file alongside its own new file, the two are separate invocations joined by
`&&`, so the step's `Expected:` names the new file's own count and that token
appears verbatim in the captured output. This is the shape D-202 makes checkable.

## Acceptance criteria and their owning steps

The acceptance criteria are quoted verbatim from `spec.md`, which is the single
SAOC inventory (C-008); no step paraphrases one.

| id | acceptance criterion (verbatim from spec.md) | step |
|---|---|---|
| AC-1 | AC-1: the Evidence parser · extracts · one entry per acceptance-criterion id from the `## Evidence` section of build-log.md, each carrying its command, its captured output and its verdict · when an entry declares several ids then each declared id counts as covered by that entry | step-2 |
| AC-2 | AC-2: the Evidence parser · accepts · an entry without an explicit verdict line as an implicit pass claim · when the entry carries at least one command line and non-empty captured output | step-2 |
| AC-3 | AC-3: the Evidence parser · requires · an explicit non-empty reason on a deferred entry · when the entry declares the deferred verdict and the reason is empty then the entry is malformed | step-2 |
| AC-4 | AC-4: the build ack gate · blocks · a build whose Evidence section leaves an acceptance criterion parsed by spec_saoc without any entry · when the track is M or L and the operator override in meta.json is unset | step-3 |
| AC-5 | AC-5: the build ack gate · re-executes · the command of every Evidence entry in the project root under a per-entry time budget · when the ack runs on the persisting path, and it executes nothing on the read-only probe path | step-3 |
| AC-6 | AC-6: the build ack gate · blocks · an Evidence entry claiming pass whose re-executed command exits non-zero · when the track is M or L | step-3 |
| AC-7 | AC-7: the verification runner · records · the distinct state unverified together with its reason for a command that exceeded its budget or could not be launched · when the outcome is unknown, so that the result is never reported as failing and never as passing | step-1 |
| AC-8 | AC-8: the build ack gate · re-executes · the VERIFY command of every impl-plan step and compares the outcome with the step Expected field · when the track is M or L and an impl-plan exists | step-4 |
| AC-9 | AC-9: the build ack gate · reports · a step whose VERIFY value is a placeholder or is not runnable as a blocking finding naming the step id · when the track is M or L, and as a surfaced advisory when the track is S | step-4 |
| AC-10 | AC-10: ac_test_coverage · verifies · AC-referencing test nodes with a per-node time budget so that one node exceeding it leaves its sibling nodes classified from their own results · when more than one node is requested | step-5 |
| AC-11 | AC-11: ac_test_coverage · classifies · a node that exceeded its budget as unverified with the reason slow · when the node produced no pass or fail outcome, instead of the weak not-passing message | step-5 |
| AC-12 | AC-12: the verification time budgets · resolve · through settings.resolve from a dedicated settings.yml namespace with documented defaults · when the operator sets the keys in the project settings file then the resolved budgets change accordingly | step-1 |
| AC-13 | AC-13: consistency_check · fails · a FACT item in spec.md, design/options.md or impl-plan.md whose src does not name an existing project code or config file · when the src path is missing, unparseable, or resolves inside a ticket directory | step-6 |
| AC-14 | AC-14: items_verify · reports · the undecidable share of FACT items as a named ratio in its stats output · when the verification log holds at least one recorded run | step-6 |
| AC-15 | AC-15: the gate track scaling · applies · off on XS, surface-only on S and blocking on M and L with a named meta.json override on M and L · when the track is read from meta.json at ack | step-3 |
| AC-16 | AC-16: the whole verification arm · degrades · to a surfaced unverified advisory carrying the reason and never to a silent pass · when the runner itself cannot start or the gate raises | step-7 |
| AC-17 | AC-17: the Evidence parser · maps · the twelve existing entries of the KLC-105 build-log Evidence section onto AC-1 through AC-12 without editing that file · when the section is parsed in structure-only mode | step-2 |
| AC-18 | AC-18: the build ack gate · rejects · a fixture Evidence section holding pasted prose and one unattributed fenced block · when the track is M | step-3 |
| AC-19 | AC-19: the verification runner · treats · every Evidence and VERIFY command as an opaque string with no language, framework or test-runner assumption · when a command is executed or classified | step-1 |
| AC-20 | AC-20: core/agents/impl.md, the regenerated klc-plugin/agents/impl.md and docs/process.md · document · the per-AC Evidence entry shape and the unverified state · when the build contract is read by an agent or an operator | step-8 |

## step-1 — bounded verification runner and the `verify.*` budget namespace

- Goal: give the whole framework one bounded command executor whose result is
  `pass`, `fail` or `unverified` with a named reason, and one settings namespace
  that supplies its budgets.
- RED: `tests/integration/test_klc115_runner.py::test_command_exceeding_budget_is_unverified_with_reason` (test-plan row AC-7) — a command that sleeps past a one-second budget must return state `unverified` with a reason naming the budget, never `fail` and never `pass`.
- GREEN: add `core/skills/verify_runner.py` holding `Verdict`, the three state
  constants, the closed reason-token set, and `run()`; move
  `index_refresh._kill_tree` and `index_refresh._spawn` into it as the public
  `kill_tree` and `spawn` (with a new `shell` keyword) and leave the two private
  names in `index_refresh` as one-line delegations; add the four typed accessors
  to `core/skills/settings.py` and register the four dotted keys in
  `core/skills/validate_config._SETTINGS_SCHEMA` as `posint` in the same commit,
  because an unregistered key is reported as `unknown key` (F-107).
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_runner.py::test_command_exceeding_budget_is_unverified_with_reason tests/integration/test_klc115_runner.py::test_command_that_cannot_be_launched_is_unverified_not_failed tests/integration/test_klc115_runner.py::test_runner_treats_command_as_opaque_string_no_framework_assumption tests/integration/test_klc115_runner.py::test_large_output_command_is_bounded tests/integration/test_klc115_settings_budgets.py -q`
- Expected: `7 passed` — the four selected runner nodes plus the three budget-resolution cases in `test_klc115_settings_budgets.py`.
- COMMIT: `KLC-115 step-1: bounded verification runner with pass/fail/unverified verdicts and verify.* budgets`
- Affected: `core/skills/verify_runner.py (new)`, `core/skills/index_refresh.py`, `core/skills/settings.py`, `core/skills/validate_config.py`, `tests/integration/test_klc115_runner.py (new)`, `tests/integration/test_klc115_settings_budgets.py (new)`
- Addresses: AC-7, AC-12, AC-19
- Interfaces: `verify_runner.Verdict`, `verify_runner.run`, `verify_runner.spawn`, `verify_runner.kill_tree`, `verify_runner.PASSED`, `verify_runner.FAILED`, `verify_runner.UNVERIFIED`, `settings.verify_entry_budget`, `settings.verify_step_budget`, `settings.verify_node_budget`, `settings.verify_arm_budget`
- Depends on: none
- Code sketch:

```python
# core/skills/verify_runner.py
PASSED, FAILED, UNVERIFIED = "pass", "fail", "unverified"
BUDGET_EXCEEDED, LAUNCH_ERROR, SLOW = "budget-exceeded", "launch-error", "slow"
RUNNER_UNAVAILABLE, NOT_RUN = "runner-unavailable", "not-run"
MAX_OUTPUT = 20000


@dataclass(frozen=True)
class Verdict:
    state: str          # PASSED | FAILED | UNVERIFIED
    reason: str = ""    # closed token set; "" on PASSED / FAILED
    detail: str = ""    # human sentence; KLC-117 lifts (reason, detail) verbatim
    elapsed: float = 0.0
    output: str = ""
    exit_code: int | None = None

    def advisory(self) -> str:
        return f"{self.reason}: {self.detail}" if self.reason else self.state


def spawn(cmd, *, cwd=None, env=None, shell=False):
    """Promoted from index_refresh._spawn (D-002). `shell=True` keeps an opaque
    Evidence command opaque; start_new_session still makes the shell the group
    leader, so kill_tree terminates the whole tree."""
    kw = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return subprocess.Popen(cmd, cwd=cwd, env=env, shell=shell,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, **kw)


def kill_tree(proc):
    """Promoted verbatim from index_refresh._kill_tree (F-109): POSIX killpg
    escalation, Windows taskkill. index_refresh._kill_tree now delegates here."""


def run(command, *, budget_s, cwd=None, env=None, max_output=MAX_OUTPUT) -> Verdict:
    """Execute an OPAQUE command under a wall-clock budget. Exit status alone
    decides pass/fail here — this layer parses NO output (AC-19). A consumer that
    is allowed to know a test runner (ac_test_coverage, per C-007) does its own
    attribution on Verdict.output; no other consumer may."""
    started = time.monotonic()
    try:
        proc = spawn(command, cwd=cwd, env=env, shell=isinstance(command, str))
    except OSError as exc:
        return Verdict(UNVERIFIED, LAUNCH_ERROR,
                       f"could not launch the command ({type(exc).__name__})",
                       time.monotonic() - started)
    try:
        out, _ = proc.communicate(timeout=budget_s)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        elapsed = time.monotonic() - started
        return Verdict(UNVERIFIED, BUDGET_EXCEEDED,
                       f"{elapsed:.0f}s > {budget_s:g}s budget", elapsed)
    out = (out or "")[:max_output]
    state = PASSED if proc.returncode == 0 else FAILED
    return Verdict(state, "", "", time.monotonic() - started, out, proc.returncode)
```

The four budget accessors sit on the existing four-layer ladder (F-108) and the
four dotted keys join the closed schema allow-list in the same commit:

```python
# core/skills/settings.py
def verify_entry_budget() -> int:
    return int(settings.resolve("verify.entry_budget_seconds",
                                legacy_file="profile.yml",
                                legacy_key="verify_entry_budget_seconds",
                                default=120))


def verify_step_budget() -> int:
    """verify.step_budget_seconds, default 120 — same ladder, same shape."""


def verify_node_budget() -> int:
    """verify.node_budget_seconds, default 120 — same ladder, same shape."""


def verify_arm_budget() -> int:
    """verify.arm_budget_seconds, default 600 — same ladder, same shape."""


# core/skills/validate_config.py — _SETTINGS_SCHEMA (F-107) gains four posint keys:
#   "verify.entry_budget_seconds": ("posint", None), and the three siblings.
```

- Rollback note: `index_refresh` is on the hot path of `klc intake`, `klc next`
  and `klc ack`. If the promotion misbehaves, restore the two private bodies in
  `index_refresh` from git and leave `verify_runner` standing — nothing else
  depends on it yet at this step. Confirm with
  `python3 -m pytest tests/integration/test_klc107_refresh.py -q` before committing.

## step-2 — Evidence parser

- Goal: read the `## Evidence` section of build-log.md into one entry per
  acceptance-criterion id, each carrying its command, its captured output and its
  verdict claim, in a structure-only mode that executes nothing.
- RED: `tests/integration/test_klc115_evidence_parser.py::test_entry_declaring_two_ac_ids_covers_both` (test-plan row AC-1) — a single `### AC-1, AC-2` anchor with one command line and non-empty output must yield both ids as covered, each carrying the same command/output/verdict tuple.
- GREEN: add `core/skills/evidence_gate.py` with `parse_evidence(text, ac_ids)`;
  anchor on any non-fenced line naming at least one AC id (D-003), expand the
  `AC-1..AC-6` range form (D-004), require a command line plus non-empty output
  for well-formedness, treat an absent verdict line as an implicit pass and a
  reasonless deferral as malformed, and drop ids absent from the supplied
  inventory.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_evidence_parser.py tests/integration/test_klc115_klc105_mapping.py -q --deselect tests/integration/test_klc115_evidence_parser.py::test_prose_only_evidence_section_blocks_on_m`
- Expected: `9 passed` — six parser cases plus the three real-build-log mapping cases; the seventh parser case needs the step-3 gate and is deselected here.
- COMMIT: `KLC-115 step-2: parse one Evidence entry per AC id from build-log.md`
- Affected: `core/skills/evidence_gate.py (new)`, `tests/integration/test_klc115_evidence_parser.py (new)`, `tests/integration/test_klc115_klc105_mapping.py (new)`
- Addresses: AC-1, AC-2, AC-3, AC-17
- Interfaces: `evidence_gate.parse_evidence`, `evidence_gate.evidence_section`, `evidence_gate.Entry`, `evidence_gate.PASS`, `evidence_gate.DEFERRED`, `evidence_gate.MALFORMED`
- Depends on: none
- Code sketch:

```python
# core/skills/evidence_gate.py
_AC_ID = re.compile(r"\bAC-(\d+)\b")
_RANGE = re.compile(r"\bAC-(\d+)\s*\.\.\s*AC-(\d+)\b")
_FENCE = re.compile(r"^```")
_CMD = re.compile(r"^\s*\$\s+(\S.*)$")
_VERDICT = re.compile(r"(?im)^\s*verdict:\s*(pass|deferred)\s*(?:\((.*)\))?\s*$")

PASS, DEFERRED, MALFORMED = "pass", "deferred", "malformed"


@dataclass
class Entry:
    ac_ids: list[str]
    commands: list[str]
    output: str
    verdict: str            # PASS | DEFERRED | MALFORMED
    reason: str             # non-empty when verdict is DEFERRED
    anchor_line: int


def _anchor_ids(line: str) -> list[str]:
    """Ids named by a non-fenced line. Ranges expand (D-004); order preserved."""
    ids = [f"AC-{n}" for lo, hi in _RANGE.findall(line)
           for n in range(int(lo), int(hi) + 1)]
    ids += [f"AC-{n}" for n in _AC_ID.findall(_RANGE.sub("", line))]
    return list(dict.fromkeys(ids))


def evidence_section(text: str) -> str | None:
    """The body under `## Evidence` up to the next level-2 heading, or None."""


def parse_evidence(text: str, ac_ids) -> tuple[dict[str, Entry], list[Entry]]:
    """STRUCTURE ONLY — executes nothing (C-004). Returns (by_ac_id, malformed).

    An entry runs from its anchor to the next anchor or the next heading at the
    same-or-higher level, so a trailing `### Full regression suite` block belongs
    to no AC. An entry is well formed only with at least one command line AND at
    least one non-command line inside its fences. Ids outside *ac_ids* are ignored.
    """
```

- Rollback note: not risky — the module is new and no caller reads it until
  step-3 wires it in.

## step-3 — Evidence gate: per-AC coverage, re-execution, track scaling, and the surface-not-block rule for unverified

- Goal: block a build whose Evidence section leaves an acceptance criterion
  unmapped or whose pass claim exits non-zero on re-run, surface every outcome the
  gate could not observe, and do both only on the persisting ack path, with the
  track scaling and the recorded override.
- RED: `tests/integration/test_klc115_evidence_gate.py::test_budget_exceeded_entry_surfaces_not_blocks_on_m` (test-plan revision-2 addendum row AC-6/AC-7, F-4) — a track-M fixture whose single Evidence entry claims pass and whose command sleeps past a one-second entry budget must let the ack succeed while carrying an advisory whose text contains `unverified` and `budget-exceeded`. Paired with the already-planned `test_ac_with_no_evidence_entry_blocks_on_track_m`, which must still block, so the two together pin the severity boundary D-204 draws.
- GREEN: add `evidence_gate.check_evidence(ticket, track, repo, *, run_commands)`
  returning an `ac_test_coverage`-shaped report; re-execute each entry's commands
  through `verify_runner.run` with the project root as the working directory and
  `settings.verify_entry_budget()` per entry, only when `run_commands` is true;
  resolve the mode from the track (XS off, S surface, M/L block); record a
  non-zero exit and a missing or malformed entry at that mode, and record every
  `UNVERIFIED` verdict as a surfaced advisory regardless of track (D-204);
  downgrade a block to an advisory for ids listed in
  `meta.deferred_verify_evidence` (D-005); wire the arm into
  `phase_completion.can_complete_build` with `run_commands=persist`.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_evidence_gate.py tests/integration/test_klc115_track_scaling.py tests/integration/test_klc115_evidence_parser.py::test_prose_only_evidence_section_blocks_on_m tests/integration/test_klc115_runner.py::test_read_only_probe_spawns_zero_subprocesses -q`
- Expected: `13 passed` — eight gate cases including the three new surface-not-block cases, three track-scaling cases, the parser case deselected at step-2, and the execution-free probe case.
- COMMIT: `KLC-115 step-3: block a build ack on an unmapped AC or a failing Evidence re-run, surface what could not be observed`
- Affected: `core/skills/evidence_gate.py`, `core/skills/phase_completion.py`, `tests/integration/test_klc115_evidence_gate.py (new)`, `tests/integration/test_klc115_track_scaling.py (new)`, `tests/integration/test_klc115_evidence_parser.py`, `tests/integration/test_klc115_runner.py`
- Addresses: AC-4, AC-5, AC-6, AC-15, AC-18
- Interfaces: `evidence_gate.check_evidence`, `evidence_gate.warn_lines`, `evidence_gate.Report`, `evidence_gate.Finding`
- Depends on: step-1, step-2
- Code sketch:

```python
# core/skills/evidence_gate.py
def _mode(track: str) -> str:
    t = (track or "").strip().upper()
    return "skip" if t == "XS" else ("surface" if t == "S" else "block")


def check_evidence(ticket, track, repo=None, *, run_commands: bool) -> "Report":
    mode = _mode(track)
    report = Report(track=track)
    if mode == "skip":
        return report
    ac_ids = [ac.id for ac in spec_saoc.parse_acs(_read(ticket, "spec.md"))]
    body = evidence_section(_read(ticket, "build-log.md"))
    if body is None:
        return _record(report, mode, "*", "no-evidence-section", _waived(ticket))
    by_ac, malformed = parse_evidence(body, ac_ids)
    waived = _waived(ticket)          # meta.deferred_verify_evidence (D-005)
    for ac in ac_ids:                 # AC-4 / AC-18: an unmapped id BLOCKS on M/L
        if ac not in by_ac:
            _record(report, mode, ac, "no-entry", waived)
    if not run_commands:              # C-004: the read-only probe executes NOTHING
        return report
    budget = settings.verify_entry_budget()
    root = Path(repo) if repo else _project_root()
    deadline = time.monotonic() + settings.verify_arm_budget()
    for ac, entry in by_ac.items():
        if entry.verdict != PASS:     # AC-3: a well-formed deferral is not re-run
            continue
        for command in entry.commands:
            if time.monotonic() >= deadline:
                _surface(report, ac, "unverified: arm-budget-exhausted",
                         "the arm budget was spent before this entry ran")
                break
            v = verify_runner.run(command, budget_s=budget, cwd=str(root))
            if v.state == verify_runner.FAILED:        # AC-6 — the only re-run BLOCK
                _record(report, mode, ac, "rerun-failed", waived, verdict=v)
            elif v.state == verify_runner.UNVERIFIED:  # AC-7 + D-204 — ALWAYS surface
                _surface(report, ac, f"unverified: {v.reason}", v.detail)
    return report


# `_surface` never consults `mode`: D-204 makes "we could not tell" advisory on
# every track, which is what keeps KLC-105's 294-second AC-12 entry (F-111) from
# blocking a build whose test genuinely passes. Rendered as, for example:
#   evidence: AC-12 unverified: budget-exceeded (120s > 120s budget)


# core/skills/phase_completion.py — inside can_complete_build, beside the
# existing ac_test_coverage arm and under the same degrade-not-fail guard:
#   rep = evidence_gate.check_evidence(ticket, track, repo, run_commands=persist)
#   if rep.block_reason:
#       return False, f"Evidence: {rep.block_reason}"
#   advisories += evidence_gate.warn_lines(rep)
```

- Rollback note: this is the first step that can block an ack that passes today.
  If it over-blocks on a real ticket, set `meta.deferred_verify_evidence: true`
  on that ticket to waive the arm while the fixture is corrected, rather than
  reverting the commit.

## step-4 — impl-plan step VERIFY re-execution with an isolated Expected token

- Goal: re-run each impl-plan step's `VERIFY:` command at build ack and compare
  its outcome with that step's `Expected:` field, comparing only the isolated
  outcome token so that a real plan's prose can never produce a false block.
- RED: `tests/integration/test_klc115_step_verify.py::test_real_expected_fields_never_falsely_block` (test-plan revision-2 addendum row AC-8, F-2) — one table-driven test (deliberately not parametrised, so the file's reported count stays stable) over the 25 real `Expected:` fields tabulated below: for each row `expected_token` must equal the tabulated token, each of the 13 tokens must be found in a synthetic pytest tail built from that token, and each of the 12 prose rows must classify `expected-unmatchable` rather than mismatch.
- GREEN: add `core/skills/step_verify.py` with `check_steps(ticket, track, repo, *, run_commands)`
  and the public `expected_token(expected)`; read each step through
  `impl_plan_check.extract_step_fields` (F-105 — the field arrives with its
  backticks and prose intact, which is why isolation is needed); treat a
  placeholder or unlaunchable command as a blocking finding on M/L and a surfaced
  advisory on S (AC-9, D-205); compare only the isolated token, anchored so a
  shorter count cannot match inside a longer number; surface
  `expected-unmatchable` when no token exists and `unverified` when the re-run
  exceeded its budget (D-204); surface a single advisory when impl-plan.md is
  absent; wire the arm into `phase_completion.can_complete_build`.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_step_verify.py -q`
- Expected: `9 passed` — the five originally planned step cases plus the four token-isolation cases this revision adds.
- COMMIT: `KLC-115 step-4: re-execute each impl-plan step VERIFY and compare only the isolated Expected token`
- Affected: `core/skills/step_verify.py (new)`, `core/skills/phase_completion.py`, `tests/integration/test_klc115_step_verify.py (new)`
- Addresses: AC-8, AC-9
- Interfaces: `step_verify.check_steps`, `step_verify.warn_lines`, `step_verify.expected_token`, `step_verify.Report`, `step_verify.Finding`
- Depends on: step-1, step-3
- Code sketch:

```python
# core/skills/step_verify.py
# D-202: a CLOSED outcome vocabulary. A generic "count followed by a word" rule
# would lift "2 parser tests" out of KLC-113 step-6 and demand it in the output.
_WORD = r"(?:passed|failed|skipped|xfailed|xpassed|errors?|deselected|warnings?)"
_TOKEN = re.compile(rf"\d+\s+{_WORD}(?:\s*,\s*\d+\s+{_WORD})*", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join((text or "").replace("`", " ").split()).lower()


def expected_token(expected: str) -> str:
    """Isolate the outcome token from a step's raw `Expected:` field (F-2/D-202).

    Returns "" when the field is prose, which the caller surfaces as
    `expected-unmatchable` rather than blocking."""
    m = _TOKEN.search(_norm(expected))
    return m.group(0) if m else ""


def _token_in_output(token: str, output: str) -> bool:
    """`4 passed` must NOT match inside `24 passed`, so anchor the leading digit."""
    return bool(re.search(r"(?<!\d)" + re.escape(token), _norm(output)))


def check_steps(ticket, track, repo=None, *, run_commands: bool) -> "Report":
    report, mode = Report(track=track), _mode(track)
    if mode == "skip":
        return report
    plan = _read(ticket, "impl-plan.md")
    if not plan.strip():                       # AC-8 is scoped to "an impl-plan exists"
        return _surface(report, "no-impl-plan",
                        "impl-plan.md is absent, so the step VERIFY re-run is skipped")
    budget = settings.verify_step_budget()
    for step in impl_plan_check.parse_impl_plan_steps(plan):
        fields = impl_plan_check.extract_step_fields(step["body"])
        command, expected = fields["verify"], fields["expected"]
        if not command or _placeholder(command):        # AC-9
            _record(report, mode, step["id"], "verify-placeholder")
            continue
        if not run_commands:
            continue                                     # C-004: probe executes nothing
        v = verify_runner.run(command, budget_s=budget, cwd=_root(repo))
        if v.state == verify_runner.UNVERIFIED:
            if v.reason == verify_runner.LAUNCH_ERROR:   # AC-9 "is not runnable" — D-205
                _record(report, mode, step["id"], "verify-unrunnable", verdict=v)
            else:                                        # a budget overrun — D-204
                _surface(report, step["id"], f"unverified: {v.reason}", v.detail)
            continue
        if v.state == verify_runner.FAILED:
            _record(report, mode, step["id"], "verify-failed", verdict=v)
            continue
        token = expected_token(expected)
        if not token:
            _surface(report, step["id"], "expected-unmatchable",
                     "Expected is prose, so the step was judged on exit status alone")
        elif not _token_in_output(token, v.output):      # AC-8
            _record(report, mode, step["id"], "expected-mismatch", verdict=v)
    return report
```

The rule is not asserted in the abstract. The table below is every `Expected:`
field this project has actually written in the three impl-plans the review named,
read through `impl_plan_check.extract_step_fields` exactly as `check_steps` reads
it, and it is the literal fixture the RED test embeds:

```text
ticket   step     isolated token        verdict   raw Expected field as extract_step_fields returns it
--------------------------------------------------------------------------------------------------------------------------------------------
KLC-103  step-1   14 passed             compare   `14 passed` — 6 in `test_klc103_shared_accessor.py` (2 more than originally sketched: `test_accessor_load_raises_on_wrong_shape_regardless_of_required` and `test_accessor_load_absent_degrades_only_when_not_required`, both baseline coverage for D-2's degrade/raise split), 2 in `test_klc103_schema_canonical.py`, 6 pre-existing in `test_deterministic_inventory.py`
KLC-103  step-2   28 passed             compare   `28 passed`
KLC-103  step-3   10 passed, 2 skipped  compare   `10 passed, 2 skipped` (2 pre-existing `@unittest.skip` rows — profile.yml detection override, removed before this ticket — not 1 as originally estimated)
KLC-103  step-4   16 passed             compare   `16 passed`
KLC-103  step-5   14 passed             compare   `14 passed` — 6 from `test_rules_typescript.py` (the 4 originally planned plus the two F-1 additions), 1 nesting floor, and 7 parametrised AC-1 cases (`typescript/.ts`, `tsx/.tsx`, `javascript/.js`, `python/.py`, `rust/.rs`, `cpp/.cpp`, `cpp-unreal/.h`)
KLC-103  step-6   4 passed              compare   `4 passed` from the executor file, then the full suite exits 0 with 0 failed
KLC-107  step-1   -                     surface   the first command reports all new cases passed; the second reports the pre-existing doctor suites still passing unmodified.
KLC-107  step-2   -                     surface   the first reports both cases passed; the second reports the pre-existing `test_doctor_without_project_deps` and `test_doctor_default_mode_missing_tools` still passing (both assert exit 0 and `DOCTOR_OK`, which a warn-only check preserves).
KLC-107  step-3   -                     surface   the first reports all five lock cases passed, including the two-process race; the second reports the pre-existing update and init suites still passing unmodified.
KLC-107  step-4   -                     surface   all five groups pass, including the grandchild-kill assertion and the boundary pair.
KLC-107  step-5   -                     surface   the first reports the whole refresh file passing, including the three ordering assertions; the second reports every pre-existing intake, next and ack suite still passing — in particular that the new "uninitialised" stderr line does not break their substring-based output assertions.
KLC-107  step-6   -                     surface   the first reports both the positive and the invalid-value case passed; the second reports the pre-existing settings and config-hygiene suites still passing.
KLC-107  step-7   -                     surface   all six detection cases and the worktree resolution case pass.
KLC-107  step-8   -                     surface   the first reports the whole install file passing, including the fail-open shim case, the chaining, the idempotency and the manager-files-untouched assertions; the second reports the pre-existing install and hook suites still passing.
KLC-107  step-9   -                     surface   the first reports the whole doctor file passing, including all three recorded-mode branches and the JSON schema assertion over the five new checks; the second reports the pre-existing doctor suites still passing.
KLC-107  step-10  -                     surface   the new stale file passes and all three pre-existing `_compute_stale` callers pass, with only the two closure assertions in `test_update_stale.py` changed.
KLC-107  step-11  -                     surface   both the two-count case and the old-schema case pass.
KLC-107  step-12  -                     surface   the two new files pass; the coverage probe prints `BLOCK_REASON None` and reports AC-20 to AC-24 as non-blocking undetermined findings; and the full suite is green.
KLC-113  step-1   27 passed             compare   `27 passed` (4 new include tests, 12 drift-guard tests, 11 pre-commit gate tests). No prompt carries a directive yet, so the regenerated bytes are identical to the committed ones and the drift-guard stays green.
KLC-113  step-2   30 passed             compare   `30 passed` (7 include tests, 12 drift-guard tests, 11 pre-commit gate tests).
KLC-113  step-3   20 passed             compare   `20 passed` (8 include tests, 12 drift-guard tests).
KLC-113  step-4   13 passed             compare   `13 passed` (1 prompt-honesty test, 12 drift-guard tests).
KLC-113  step-5   10 passed             compare   `10 passed`.
KLC-113  step-6   55 passed             compare   `55 passed` (2 parser tests, 3 card tests, 8 existing card-compression tests, 23 existing task-brief tests, 19 existing impl-plan-check tests).
KLC-113  step-7   26 passed             compare   `26 passed` (2 byte-budget tests, 13 existing docs-consolidation tests, 11 existing precommit-plugin-sync tests).
--------------------------------------------------------------------------------------------------------------------------------------------
totals: 13 compared, 12 surfaced as expected-unmatchable, 0 false blocks
```

Under the superseded whole-field comparison all 13 of the compared rows would
have blocked, because every one of them carries backticks, an em dash or a
parenthetical that terse pytest output never contains — including the three that
look bare, since `28 passed` still arrives wrapped in backticks (F-105). That is
the regression this step closes.

- Rollback note: if the token vocabulary proves too narrow for a plan written in
  another framework's idiom, widen `_WORD` rather than falling back to the
  whole-field comparison; a missing token surfaces, so a narrow vocabulary is the
  safe failure direction.

## step-5 — per-node budgets in `ac_test_coverage`, with the existing outcome parser re-homed

- Goal: stop one slow test node from marking every acceptance criterion of a
  ticket weak, by verifying one node per invocation under its own budget, while
  keeping the existing pytest outcome attribution so a skipped node can still
  never count as passing.
- RED: `tests/integration/test_klc115_ac_budget.py::test_skipped_node_is_unverified_and_still_counts_weak` (test-plan revision-2 addendum row AC-11, F-1) — a node whose only test is `@pytest.mark.skip` exits 0, so the new per-node path must classify it `unverified` with the reason `skipped`, must not report it as passing, and must still count it toward the weak population; the companion `tests/test_ac_test_coverage.py::test_verify_passing_skip_is_not_passing` must stay green unmodified through the same code path.
- GREEN: extract the outcome-attribution loop that already lives inside
  `_verify_passing` (F-103, `core/skills/ac_test_coverage.py:450`) into a
  module-level `_attribute_outcomes(output, nodes)`; add `_verify_nodes`, which
  runs each collected node through `verify_runner.run` under
  `settings.verify_node_budget()` with the same `--tb=no -v` invocation and calls
  that shared helper on the captured output; keep `_verify_passing` as a thin
  boolean adapter over it so the module's own callers and
  `tests/test_ac_test_coverage.py` are untouched; render a budget overrun as
  `unverified: slow` and exclude only the inconclusive reasons from the weak,
  drift and miss counts.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_ac_budget.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/test_ac_test_coverage.py -q`
- Expected: `6 passed` from the new budget file, then `tests/test_ac_test_coverage.py` reports its existing green count with zero failures.
- COMMIT: `KLC-115 step-5: per-node budget in ac_test_coverage, a slow node is unverified and a skipped node still never passes`
- Affected: `core/skills/ac_test_coverage.py`, `tests/integration/test_klc115_ac_budget.py (new)`
- Addresses: AC-10, AC-11
- Interfaces: `ac_test_coverage.UNVERIFIED` (new module constant); `ac_test_coverage.check`, `ac_test_coverage.warn_lines`, `ac_test_coverage.Report` and `ac_test_coverage.Finding` keep their existing shape
- Depends on: step-1
- Code sketch:

```python
# core/skills/ac_test_coverage.py
UNVERIFIED = "unverified"        # the honest third state beside COVERED/DRIFT/WEAK/MISS

# D-201: only these mean "the gate could not observe". `skipped` and `uncollected`
# are definite negative observations and keep today's WEAK treatment, so a skipped
# test still cannot evade the gate (F-104).
_INCONCLUSIVE = frozenset({"slow", "arm-budget-exhausted",
                           "launch-error", "runner-unavailable"})


def _attribute_outcomes(run_out: str, nodes) -> tuple[set[str], set[str]]:
    """The EXISTING FIX-3/FIX-5/FIX-B attribution loop, moved out of
    _verify_passing unchanged (F-103) so both the boolean path and the tri-state
    path read one parser. Returns (passed_any, bad_any): a `-v` progress line
    `<nodeid> <OUTCOME>` or a summary line `<OUTCOME> <nodeid>` is located by its
    outcome TOKEN, the node-id is reconstructed around it, and a parametrised
    variant `node[param]` attributes to its base node. SKIPPED and XFAIL add to
    neither set, which is exactly why a skip is not a pass."""


def _verify_nodes(node_ids, repo=None, tests_root=None) -> dict[str, tuple[str, str]]:
    """One pytest invocation PER NODE under verify.node_budget_seconds (D-006), so
    a node that exceeds its budget can never mark a sibling not-passing — replacing
    the single batched run with its hardcoded timeout=300 (F-102). Returns
    {node_id: (state, reason)} with state in {pass, fail, unverified}."""
    out, budget = {}, settings.verify_node_budget()
    deadline = time.monotonic() + settings.verify_arm_budget()
    collected = _collect_per_file(node_ids, repo, tests_root)   # existence floor, unchanged
    for node in node_ids:
        if node not in collected:
            out[node] = (verify_runner.UNVERIFIED, "uncollected")   # weak, as today
            continue
        if time.monotonic() >= deadline:
            out[node] = (verify_runner.UNVERIFIED, "arm-budget-exhausted")
            continue
        cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
               node, "--tb=no", "-v"]
        v = verify_runner.run(cmd, budget_s=budget, cwd=_cwd(repo, tests_root))
        if v.state == verify_runner.UNVERIFIED:
            reason = ("slow" if v.reason == verify_runner.BUDGET_EXCEEDED
                      else v.reason)                                # AC-11
            out[node] = (verify_runner.UNVERIFIED, reason)
            continue
        # The command ran. AC-19 keeps the RUNNER on exit status alone, but pytest
        # exits 0 for an all-skipped node, so the pytest-aware layer (the one
        # C-007 permits) attributes the real outcome from the -v lines.
        passed, bad = _attribute_outcomes(v.output, [node])
        if node in bad:
            out[node] = (verify_runner.FAILED, "")
        elif node in passed:
            out[node] = (verify_runner.PASSED, "")
        else:
            out[node] = (verify_runner.UNVERIFIED, "skipped")       # F-1: never a pass
    return out


def _verify_passing(node_ids, repo=None, tests_root=None) -> dict[str, bool]:
    """Boolean adapter kept for the existing in-module callers and tests. A skipped
    node lands UNVERIFIED, so this still returns False for it and
    test_verify_passing_skip_is_not_passing keeps asserting what it asserts today."""
    return {n: st == verify_runner.PASSED
            for n, (st, _reason) in _verify_nodes(node_ids, repo, tests_root).items()}


# _record gains an UNVERIFIED arm that never emits the WEAK text
#   "referencing test is a placeholder / uncollected / not passing"
# for a node whose reason is in _INCONCLUSIVE; _evaluate excludes exactly those
# nodes from the weak/drift/miss counts and surfaces them as `unverified: <reason>`.
```

- Rollback note: this changes the classification of every M/L ticket's AC
  coverage. If the per-node cost proves unacceptable in practice, raise
  `verify.node_budget_seconds` and revisit the adaptive batch-then-split variant
  recorded as the rejected alternative in D-006. Do not revert `_attribute_outcomes`
  into `_verify_passing`: the shared helper is what keeps one parser in the module.

## step-6 — FACT sources must name project code, graduated so no in-flight ticket breaks

- Goal: make a FACT item in spec.md, design/options.md or impl-plan.md fail
  consistency when its `src` does not name an existing project code or config
  file, blocking only where the item opted in or the ticket is new, warning
  everywhere else, and report the unverifiable share of FACT items as a ratio.
- RED: `tests/integration/test_klc115_fact_source.py::test_pre_epoch_ticket_without_evidence_read_warns_instead_of_blocking` (test-plan revision-2 addendum row AC-13, F-3) — a fixture ticket whose `meta.created` is one day before `FACT_SOURCE_RULE_EPOCH` and whose spec.md holds a FACT with a comma-joined multi-path `src` must make `consistency_check.check_ticket` return an empty error list and append one warning naming the item; the sibling case with `meta.created` one day after the epoch must return a blocking error for the same item.
- GREEN: add `src_kind(src, repo)` returning `code`, `ticket-artifact`, `missing`
  or `unparseable` and `fact_source_enforced(item, meta)` implementing D-203's
  predicate, both in `core/skills/items_verify.py` (D-008 — one rule for the gate
  and the metric); call them from `consistency_check.check_ticket` over the FACT
  items of the three named artifacts only, matched by exact ticket-relative path
  so a `_superseded/` snapshot is out of scope (A-005); route non-enforced
  violations into the new `warnings` list that `cmd_check` prints without
  touching the exit code (D-206); add the `undecidable_share` ratio to
  `items_verify.cmd_stats`.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_fact_source.py tests/integration/test_klc115_items_verify_metric.py -q`
- Expected: `9 passed` — eight FACT-source cases including the live-ticket guard, plus the undecidable-share ratio case.
- COMMIT: `KLC-115 step-6: FACT src must name project code, enforced for opted-in items and new tickets, warned elsewhere`
- Affected: `core/skills/items_verify.py`, `core/skills/consistency_check.py`, `tests/integration/test_klc115_fact_source.py (new)`, `tests/integration/test_klc115_items_verify_metric.py (new)`
- Addresses: AC-13, AC-14
- Interfaces: `items_verify.src_kind`, `items_verify.fact_source_enforced`, `items_verify.FACT_SOURCE_ARTIFACTS`, `items_verify.FACT_SOURCE_RULE_EPOCH`; `consistency_check.check_ticket` keeps its `list[str]` return and gains an optional `warnings` keyword
- Depends on: none
- Code sketch:

```python
# core/skills/items_verify.py
FACT_SOURCE_ARTIFACTS = ("spec.md", "design/options.md", "impl-plan.md")

# D-203 / A-004: the day AFTER this rule lands. If step-6 is committed later than
# 2026-09-17, bump this constant to the day after that commit; the tests below
# build their fixture dates relative to the constant, never from today, so a bump
# cannot break them.
FACT_SOURCE_RULE_EPOCH = "2026-09-18"


def src_kind(src: str, repo: Path) -> str:
    """Classify a FACT `src=` value (AC-13, D-008) — the ONE rule the gate and the
    metric share. `code` is the only acceptable kind for the three artifacts."""
    src = (src or "").strip()
    if not src:
        return "missing"
    m = SRC_FILE_LINE_RE.match(src)        # <path> or <path>:<line> only (F-106)
    if not m:
        return "unparseable"               # a range form, a comma-joined pair, a shell command
    path = m.group(1).replace("\\", "/")
    if path.startswith(".klc/tickets/"):
        return "ticket-artifact"
    return "code" if (repo / path).exists() else "missing"


def fact_source_enforced(item, meta) -> bool:
    """D-203: block only for an opted-in item or a ticket created on/after the
    epoch; warn for everything older, so a ticket already in flight cannot be
    broken by a rule that did not exist when its artifacts were written (F-110,
    F-112). An absent or unparseable created date warns, because the property
    being protected is 'no in-flight ticket breaks'."""
    if str(item.attrs.get("evidence", "")).strip().lower() == "read":
        return True                         # KLC-116's opt-in implies a file:line src
    created = str((meta or {}).get("created", ""))[:10]
    return created >= FACT_SOURCE_RULE_EPOCH    # ISO-8601 dates compare lexically


def cmd_stats(args) -> int:
    """AC-14: the undecidable share becomes a named ratio, not a raw count."""
    share = round(counts["undecidable"] / runs, 3) if runs else 0.0
    print(json.dumps({"runs": runs, "counts": counts, "undecidable_share": share}))


# core/skills/consistency_check.py — inside check_ticket, after the items.validate
# call at line 81; `warnings` is an optional out-list so the return value keeps
# meaning "blocking errors" and the pre-commit exit code keeps its meaning (D-206).
for item in items_verify.iter_facts(klc_ticket_dir(ticket)):
    rel = str(item.file.relative_to(klc_ticket_dir(ticket))).replace("\\", "/")
    if item.type != "FACT" or rel not in items_verify.FACT_SOURCE_ARTIFACTS:
        continue                            # exact match keeps _superseded/ snapshots out (A-005)
    kind = items_verify.src_kind(item.attrs.get("src", ""), _repo_root())
    if kind == "code":
        continue
    line = (f"{ticket}: {item.id} in {rel}: src must name a project code or "
            f"config file ({kind})")
    if items_verify.fact_source_enforced(item, meta):
        errs.append(line)
    elif warnings is not None:
        warnings.append(line + " — warned only, predates FACT_SOURCE_RULE_EPOCH")
```

The guard test that closes F-3 runs the finished rule over the real tickets under
`.klc/tickets/`, and asserts the predicate rather than a fixed count, so it stays
true as tickets are created and archived:

```python
# tests/integration/test_klc115_fact_source.py
def test_no_live_ticket_blocks_unless_opted_in_or_created_after_the_epoch():
    """F-3: KLC-118 is mid-build on this branch with three offending src values
    (F-112) and its routine build commits must keep passing the pre-commit hook."""
    for ticket in live_tickets():
        warnings = []
        for err in consistency_check.check_ticket(ticket, warnings=warnings):
            assert not err.endswith("src must name a project code or config file"), err
        blocking = [e for e in errs_of(ticket) if "src must name" in e]
        for item in offending_items(ticket):
            assert (item_opted_in(item) or created_on_or_after_epoch(ticket)), (
                f"{ticket}/{item.id} would block although it predates the rule")
```

- Rollback note: if the graduated predicate still blocks a ticket it should not,
  raise `FACT_SOURCE_RULE_EPOCH` rather than reverting the commit — the rule then
  degrades to warn-only everywhere, which is the intended safe direction.

## step-7 — arm-level degrade guard: unverified, never a silent pass

- Goal: make the whole verification arm degrade to a surfaced unverified advisory
  carrying its reason whenever the runner cannot start or a gate raises, and never
  to a silent pass.
- RED: `tests/integration/test_klc115_runner.py::test_runner_launch_failure_degrades_to_surfaced_advisory_never_silent_pass` (test-plan row AC-16) — with the runner made unavailable, the ack must succeed while carrying a non-empty advisory naming the reason.
- GREEN: wrap the three new arms in `phase_completion.can_complete_build` in one
  guard that mirrors the existing `ac-coverage: check did not run` pattern,
  appending `verify: arm did not run — <reason>: <detail> (verification unverified)`
  and asserting that the advisory list is non-empty on every exception path.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_runner.py::test_runner_launch_failure_degrades_to_surfaced_advisory_never_silent_pass tests/integration/test_klc115_runner.py::test_gate_exception_never_silently_passes_with_no_advisory -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_build_evidence_gate.py -q`
- Expected: `2 passed` from the two degrade nodes, then `tests/integration/test_build_evidence_gate.py` reports its existing green count with zero failures.
- COMMIT: `KLC-115 step-7: the verification arm degrades to a surfaced unverified advisory, never a silent pass`
- Affected: `core/skills/phase_completion.py`, `tests/integration/test_klc115_runner.py`
- Addresses: AC-16
- Interfaces: none
- Depends on: step-3, step-4, step-5
- Code sketch:

```python
# core/skills/phase_completion.py — can_complete_build
for name, arm in (("evidence", evidence_gate.check_evidence),
                  ("step-verify", step_verify.check_steps)):
    try:
        rep = arm(ticket, track, repo, run_commands=persist)
    except Exception as exc:
        # C-003 in its honest form: a surprise is UNVERIFIED with the reason
        # named, never a silent pass and never a claim about the tests.
        advisories.append(
            f"verify[{name}]: arm did not run — runner-unavailable: "
            f"{type(exc).__name__} (verification unverified)")
        continue
    if rep.block_reason:
        return False, f"{name}: {rep.block_reason}"
    advisories += arm_warn_lines(rep)
assert advisories or not _arm_raised, "an arm that raised must leave an advisory"
```

- Rollback note: not risky on its own — the guard only widens what the ack
  tolerates, so reverting it restores a crash, not a false pass.

## step-8 — document the Evidence entry shape, the unverified state and the FACT rule

- Goal: make the build contract in the impl prompt, its deployed plugin copy and
  the process documentation describe the per-AC Evidence entry, the unverified
  state and the graduated FACT-source rule, so an agent and an operator read the
  same rule the gate enforces.
- RED: `tests/integration/test_klc115_docs_contract.py::test_impl_prompts_and_process_doc_describe_evidence_shape_and_unverified_state` (test-plan row AC-20) — `core/agents/impl.md`, `klc-plugin/agents/impl.md` and `docs/process.md` must each describe the command, output and verdict shape and the unverified state.
- GREEN: rewrite the Evidence-block section of `core/agents/impl.md` to specify
  the anchor-plus-fence entry and to state plainly that a budget overrun is
  reported as unverified rather than as a failing test; update the build sections
  of `docs/process.md` with the same contract and with D-203's epoch rule for FACT
  sources; add the four `verify.*` knobs to the settings table in
  `docs/configuration.md`; run `python3 core/skills/plugin_gen.py` and stage the
  regenerated `klc-plugin/` files in the same commit (C-005).
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc115_docs_contract.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/test_plugin_agents_in_sync.py -q`
- Expected: `2 passed` from the docs-contract file, then `tests/test_plugin_agents_in_sync.py` reports its existing green count with zero failures.
- COMMIT: `KLC-115 step-8: document the per-AC Evidence entry shape, the unverified state and the FACT source rule`
- Affected: `core/agents/impl.md`, `klc-plugin/agents/impl.md`, `docs/process.md`, `docs/configuration.md`, `tests/integration/test_klc115_docs_contract.py (new)`
- Addresses: AC-20
- Interfaces: none
- Depends on: step-2, step-3
- Code sketch:

```text
## Evidence block (required before IMPL_ALL_GREEN)

Append an `## Evidence` section to build-log.md with ONE entry per acceptance
criterion in spec.md. An entry is a heading naming its acceptance-criterion ids,
an optional `verdict:` line, and a fenced block holding the command (a line
starting with a dollar sign and a space) and its real pasted output.

    ### AC-1, AC-2 — the parser extracts one entry per acceptance criterion
    verdict: pass

    (fenced block: the command line and its pasted output)

Rules:
- Every acceptance criterion parsed from spec.md needs an entry, or the ack is
  blocked on M and L. An entry may cover several ids.
- No `verdict:` line means you are claiming pass. Use `verdict: deferred(<reason>)`
  with a non-empty reason when a check could not run.
- `klc ack` RE-EXECUTES each entry's command in the project root under
  `verify.entry_budget_seconds`. A non-zero exit BLOCKS. A budget overrun or a
  launch error is reported as `unverified` with the reason named — it SURFACES on
  every track and is neither a pass nor a claim that your tests failed.
- Paste real output. Do not fabricate or summarise.
- A FACT item in spec.md, design/options.md or impl-plan.md must cite a project
  code or config file as `src=<path>:<line>`. For a ticket created on or after
  FACT_SOURCE_RULE_EPOCH, or for any item carrying `evidence=read`, a bad source
  fails consistency; for older tickets it is warned, not failed.
```

- Rollback note: the drift-guard `tests/test_plugin_agents_in_sync.py` fails the
  commit if `plugin_gen.py` was not re-run, so a stale plugin copy cannot ship.
