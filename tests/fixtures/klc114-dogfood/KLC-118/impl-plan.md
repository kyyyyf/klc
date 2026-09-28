---
ticket: KLC-118
track: M
authority: agent
last_generated: 2026-09-16T19:25:00Z
option: A
options_ref: design/options.md
adr_ref: design/adr.md
---

# KLC-118 — implementation plan

Picked option A (see `design/options.md`): the card writer gains a render mode, the mode and the
card path are published by `phase_resolver`, the card root moves to `.klc/scratch` behind one
resolver, and the card measurement goes through the existing `write_token_metrics`.

Order of risk: the card **location** moves first (it breaks the most existing assertions and every
later step depends on one agreed path), then the **content** modes (the golden files must be frozen
from a content-unchanged renderer), then the **executors**, then telemetry, then the artefact
universe and the migration, then the size gate and the documentation.

Run everything with `PROJECT_ROOT=/home/ek/projects/klc`.

## step-1 — Resolve every card path through one helper rooted outside the ticket tree — DONE

> [!DECISION D-118-1] owner=impl-agent date=2026-09-17T00:00:00Z refs=step-1,F-1
> impl-plan-review finding F-1 (HIGH) identified a sixth card reader,
> `vscode-extension/src/klcReader.ts:promptCardPath`, that no step named and
> that would silently start returning `null` once AC-7 moved cards off the
> ticket tree. Folded the fix into step-1 (same "every reader resolves the
> same path" goal) rather than adding a new step, since it is a pure
> TS+source-regex-test change independent of the Python plumbing: added
> `cardRoot()` (mirrors `klc_card_root()`) and made `promptCardPath` probe it
> before the ticket-dir fallback. This widens `meta.json:affected_modules` to
> include `vscode-extension/src` (CLAUDE.md: "update affected_modules rather
> than fight scope"). F-1 also flagged that `impl-plan.md`'s own citation of
> `test_klc072_dispatch.py` "lines ~281-287" as ticket-dir-literal fixture code
> was wrong — that range is `test_reader_source_resolves_build_step_card`, a
> source-regex check against this exact reader. The regression rewrite those
> lines actually describe (the ticket-dir fixtures at
> `test_status_build_work_names_step_card` etc., lines ~142-193) needed NO
> change: `artefacts.card_path()`'s existence-based fallback (canonical root,
> then ticket dir) already resolves them correctly. See `build-log.md` for
> the full F-1/F-2/F-3/D-1/D-2 assessment.

- Goal: phase and step cards are written to `<card root>/<KEY>/<phase>/` and every reader learns
  that location from a single resolver instead of deriving it itself.
- RED: `tests/integration/test_klc118_card_path_parity.py::test_all_card_readers_resolve_the_same_written_card_path`
  (test-plan row AC-8) — render one phase card and one step card, then assert `klc status --json`,
  `klc work --json`, the path `klc step` prints, the path `klc jump` prints and
  `resolve_phase(key, phase).card_path` all resolve to the same file the render call returned.
- GREEN: add `CARD_ROOT_ENV`, `klc_card_root()` and `klc_card_path()` to `core/shared/paths.py`;
  add `card_path()` to `core/skills/artefacts.py` (canonical location, falling back to an existing
  ticket-directory copy) and re-export `CARD_ROOT_ENV` from it; point `write_prompt_card` and
  `write_step_card` at it; replace the hardcoded derivations in `core/phases/status.py:_work_card`
  and `core/phases/work.py`; add the `card_path` field to `ResolvedPhase`.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc118_card_path_parity.py tests/integration/test_work_verb.py tests/integration/test_klc072_dispatch.py tests/integration/test_step_card_compression.py tests/integration/test_autorunner.py -q`
- Expected: `1 passed` for the new file and `0 failed` overall, after rewriting the ticket-directory
  path literals in `test_work_verb.py` (lines ~84–123), `test_klc072_dispatch.py` (lines ~144–182,
  ~281–287), `test_step_card_compression.py` (`_make_ticket_env` and every returned-path assertion)
  and `test_autorunner.py` (line ~223) to the new root, as the test plan's regression section
  requires.
- COMMIT: KLC-118 step-1: resolve every prompt-card path through one helper rooted at .klc/scratch
- Affected: `core/shared/paths.py`, `core/skills/artefacts.py`, `core/skills/phase_resolver.py`,
  `core/phases/status.py`, `core/phases/work.py`,
  `tests/integration/test_klc118_card_path_parity.py` (new),
  `tests/integration/test_work_verb.py`, `tests/integration/test_klc072_dispatch.py`,
  `tests/integration/test_step_card_compression.py`, `tests/integration/test_autorunner.py`.
- Addresses: AC-7, AC-8
- Interfaces: `core/shared/paths.py: CARD_ROOT_ENV = "KLC_CARD_ROOT"`,
  `klc_card_root() -> Path`, `klc_card_path(ticket: str, phase_id: str, step: int | None = None) -> Path`;
  `core/skills/artefacts.py: card_path(ticket: str, phase_id: str, step: int | None = None) -> Path`;
  `ResolvedPhase.card_path: str | None = None`.
- Depends on: none
- Code sketch:

```python
# core/shared/paths.py
CARD_ROOT_ENV = "KLC_CARD_ROOT"

def klc_card_root() -> Path:
    """Root for DERIVED prompt cards, outside the ticket artefact tree."""
    raw = (os.environ.get(CARD_ROOT_ENV) or "").strip()
    return Path(raw).expanduser() if raw else klc_dir() / "scratch"

def klc_card_path(ticket_id: str, phase_id: str, step: int | None = None) -> Path:
    name = f"_prompt_step_{step}.md" if step is not None else "_prompt.md"
    return klc_card_root() / ticket_id / phase_id / name

# core/skills/artefacts.py
def card_path(ticket: str, phase_id: str, step: int | None = None) -> Path:
    """The one place any reader learns where a card lives. Canonical location
    first; a card left in the ticket dir by a degraded render (AC-12) or by a
    pre-migration layout is honoured only when the canonical one is absent."""
    canonical = klc_card_path(ticket, phase_id, step)
    if canonical.exists():
        return canonical
    legacy = klc_ticket_dir(ticket) / phase_id / canonical.name
    return legacy if legacy.exists() else canonical

# core/phases/work.py — publish the resolver's answer, keep the relative shape
out["prompt"] = os.path.relpath(_artefacts.card_path(ticket, pid, step), project_root())
```

## step-2 — Honour the root override and degrade to the ticket directory when it is unwritable — DONE

- Goal: the card root follows `KLC_CARD_ROOT`, ignores a meaningless value, and a root that cannot
  be written costs a warning instead of the phase transition.
- RED: `tests/integration/test_klc118_scratch_root.py::test_full_next_step_dispatch_cycle_leaves_no_prompt_cards_under_the_ticket_dir`
  and `::test_read_only_scratch_root_degrades_to_the_ticket_dir_without_failing_the_phase`
  (test-plan rows AC-7 and AC-12). The cycle test drives `klc next` and `klc step` under a temp
  `PROJECT_ROOT` and asserts `rglob("_prompt*.md")` under the ticket directory is empty; its
  dispatch-render leg is added in step-3, when a dispatch mode exists to render. The degrade test
  points the override at a `chmod 0o400` directory, wraps the render of the repository's largest
  role prompt (`core/agents/discovery.md`) in `time.perf_counter()`, and asserts no exception, a
  ticket-directory return path, a warning on stderr naming the unavailable root, and a wall-clock
  time well under one second.
- GREEN: add `_card_dir()` to `artefacts.py` — create the canonical directory, probe it for
  writability, and on `OSError` warn once to stderr and return the ticket-directory equivalent;
  a blank or unusable `KLC_CARD_ROOT` value already falls back to the default root by the step-1
  helper, so the malformed-value case needs only its assertion.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc118_scratch_root.py -q`
- Expected: `2 passed`
- COMMIT: KLC-118 step-2: honour KLC_CARD_ROOT and degrade to the ticket dir when the root is unwritable
- Affected: `core/skills/artefacts.py`, `tests/integration/test_klc118_scratch_root.py` (new).
- Addresses: AC-7, AC-12
- Interfaces: `core/skills/artefacts.py: _card_dir(ticket: str, phase_id: str) -> tuple[Path, bool]`
  (directory, degraded flag).
- Depends on: step-1
- Code sketch:

```python
def _card_dir(ticket: str, phase_id: str) -> tuple[Path, bool]:
    """(directory, degraded). Never raises: a card that cannot be written to the
    card root falls back to the ticket dir rather than failing the transition."""
    target = klc_card_root() / ticket / phase_id
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return target, False
    except OSError as exc:
        sys.stderr.write(
            f"artefacts: card root {target} unusable ({exc}); "
            f"falling back to the ticket directory\n"
        )
        fallback = klc_ticket_dir(ticket) / phase_id
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback, True
```

## step-3 — Give the card writer dispatch and paste modes, with paste byte-frozen — DONE

> [!DECISION D-118-2] owner=impl-agent date=2026-09-17T01:00:00Z refs=step-3,AC-1
> The AC-1 dispatch RED test (`test_dispatch_card_omits_role_prompt_lines_and_names_the_file`)
> initially failed for `core/agents/review.md` on a false positive: the card's
> pre-existing, byte-frozen-for-paste "## Inputs you should read" boilerplate
> contains the substring "## Inputs" (9 chars, ≥8), which is ALSO
> `review.md`'s own generic "## Inputs" section heading — nearly every
> `core/agents/*.md` file has one. This is a structural-heading coincidence,
> not a role-prompt-body leak: the design doc's empirical no-collision check
> (impl-plan-review.md) only grepped the NEW dispatch-preamble/pointer-block
> phrases, never the card's pre-existing `_INPUTS_TMPL`/`_OUTPUTS_TMPL`
> headers against arbitrary agent-authored section names. test-plan.md's own
> edge-case note already names "a heading marker... recurring by coincidence"
> as exactly the kind of hit that must not fail this check — its 8-char
> cutoff just didn't anticipate a 9-char heading. Fix: the leak-check test
> excludes bare markdown heading lines (`^#+\s`) from the ≥8-char comparison;
> real content lines (prose, bullets, code) are still checked and did
> genuinely fail before this step's GREEN change.

- Goal: a `dispatch` card carries ticket context and a pointer to the role prompt; a `paste` card is
  byte-identical to today's output.
- RED: `tests/integration/test_klc118_card_modes.py::test_dispatch_card_omits_role_prompt_lines_and_names_the_file`
  and `::test_paste_card_matches_golden_bytes_for_agent_and_checklist_phase`
  (test-plan rows AC-1 and AC-2). Freeze
  `tests/fixtures/klc118/golden/design_prompt.md` and `integrate_prompt.md` from the renderer as it
  stands after step-2 — steps 1 and 2 moved the location only, never a byte of content, so those
  captures are the pre-KLC-118 output AC-2 asks for. Extend the step-2 cycle test with its
  dispatch-render leg in the same commit.
- GREEN: add `mode` to `write_prompt_card` with the two module constants; keep the existing paste
  branch untouched; add the dispatch preamble and the pointer block; treat `KLC_CARD_INLINE=1` and
  any unrecognised mode as `paste`.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc118_card_modes.py tests/integration/test_klc118_scratch_root.py -q`
- Expected: `4 passed`
- COMMIT: KLC-118 step-3: render prompt cards in dispatch or paste mode, paste byte-frozen
- Affected: `core/skills/artefacts.py`, `tests/integration/test_klc118_card_modes.py` (new),
  `tests/fixtures/klc118/golden/design_prompt.md` (new),
  `tests/fixtures/klc118/golden/integrate_prompt.md` (new),
  `tests/integration/test_klc118_scratch_root.py`.
- Addresses: AC-1, AC-2
- Interfaces: `core/skills/artefacts.py: CARD_MODE_DISPATCH = "dispatch"`,
  `CARD_MODE_PASTE = "paste"`,
  `write_prompt_card(ticket: str, phase_id: str, meta: dict, step: int | None = None, mode: str = CARD_MODE_PASTE) -> Path`.
- Depends on: step-1, step-2
- Code sketch:

```python
CARD_MODE_DISPATCH = "dispatch"
CARD_MODE_PASTE = "paste"

_PREAMBLE_DISPATCH_TMPL = """\
# Agent prompt — {ticket} · {phase_id}:work

You are working in phase **{phase_id}**. Your subagent definition already
carries this phase's role prompt; this card adds the ticket context only.
When you claim the work is done, the human runs `klc ack {ticket}` (with
`--pick N` if required) to confirm.

"""

def _role_prompt_block(phase, mode: str) -> str:
    """Dispatch mode NEVER embeds a body — not even when the file is missing."""
    path = framework_root() / phase.prompt
    if mode == CARD_MODE_DISPATCH:
        return ("## Role prompt\n\n"
                "Already loaded: your subagent definition carries the full role "
                "prompt for this phase. Source of truth on disk (open only if you "
                f"need to re-read it):\n`{path}`\n")
    if path.exists():
        return "## Role prompt\n\n" + path.read_text(encoding="utf-8")
    return (f"## Role prompt\n\n_MISSING: `{phase.prompt}` — "
            "file referenced by phases.yml does not exist_\n")

def _resolve_mode(mode: str) -> str:
    if os.environ.get("KLC_CARD_INLINE", "").strip() == "1":
        return CARD_MODE_PASTE
    return CARD_MODE_DISPATCH if mode == CARD_MODE_DISPATCH else CARD_MODE_PASTE
```

## step-4 — Publish the mode from `phase_resolver` and wire both executors to it — DONE

> [!DECISION D-118-3] owner=impl-agent date=2026-09-17T01:30:00Z refs=step-4,F-3
> impl-plan-review finding F-3 (MEDIUM) warned the AC-4 RED test could pass
> vacuously before this step's wiring landed, since paste mode was already
> byte-frozen and verbatim after step-3. Built the RED test to spy on
> `phase_resolver.resolve_phase` itself (monkeypatching the module attribute)
> and assert `autorunner.run(...)` actually calls it with
> `executor=EXECUTOR_HEADLESS` for the dispatched phase — which genuinely
> failed before this step (autorunner never imported `phase_resolver` at
> all) and would also catch a caller wired to the wrong executor. Confirmed
> `python3 core/skills/plugin_gen.py` is a no-op for
> `klc-plugin/skills/run/SKILL.md` (bespoke, presence-guarded only per
> CLAUDE.md/plugin_gen.py's `BESPOKE_SKILLS`) — the file is edited directly,
> not regenerated.

- Goal: exactly one place decides which mode an executor gets, the headless path keeps its inlined
  role prompt, and `/klc:run` re-renders in dispatch mode right before it dispatches.
- RED: `tests/integration/test_klc118_phase_resolver.py::test_resolved_phase_publishes_card_mode_and_path_from_one_call`
  and `tests/integration/test_klc118_headless_paste.py::test_headless_dispatch_prompt_contains_role_prompt_verbatim`
  (test-plan rows AC-3 and AC-4) — the first asserts `paste` for a headless executor, `dispatch` for
  a Task executor, a `card_path` equal to what the writer returns, and greps
  `klc-plugin/skills/run/SKILL.md` plus `core/skills/autorunner.py` for a mode string hardcoded
  outside a `resolve_phase` call; the second captures the prompt a mocked provider receives and
  asserts the full text of `core/agents/review.md` is a substring of it.
- GREEN: add the keyword-only `executor` argument and the `card_mode` field to `phase_resolver`;
  make `autorunner._card_path` take its mode from `resolve_phase`; rewrite step 5c of
  `klc-plugin/skills/run/SKILL.md` to resolve with the Task executor, re-render, and pass the
  re-rendered card; then run `python3 core/skills/plugin_gen.py` and commit the regenerated
  `klc-plugin/` files (C-004).
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc118_phase_resolver.py tests/integration/test_klc118_headless_paste.py tests/integration/test_autorunner.py tests/test_plugin_agents_in_sync.py -q`
- Expected: `0 failed`, with `test_autorunner.py::test_dispatch_uses_rendered_card_not_generic_prompt` additionally asserting the pinned `paste` mode at the new root.
- COMMIT: KLC-118 step-4: publish card_mode from phase_resolver and wire both executors to it
- Affected: `core/skills/phase_resolver.py`, `core/skills/autorunner.py`,
  `klc-plugin/skills/run/SKILL.md`, `klc-plugin/` (regenerated),
  `tests/integration/test_klc118_phase_resolver.py` (new),
  `tests/integration/test_klc118_headless_paste.py` (new),
  `tests/integration/test_autorunner.py`.
- Addresses: AC-3, AC-4
- Interfaces: `core/skills/phase_resolver.py: resolve_phase(ticket: str, phase_id: str, *, executor: str = "headless") -> ResolvedPhase`,
  `ResolvedPhase.card_mode: str = "paste"`.
- Depends on: step-1, step-3
- Code sketch:

```python
# core/skills/phase_resolver.py
EXECUTOR_TASK = "task"
EXECUTOR_HEADLESS = "headless"

def _card_mode(executor: str) -> str:
    # Fail-safe: anything that is not an explicit Task dispatch keeps the role
    # prompt inlined (C-003), so a miswired caller sends too much, never too little.
    return _artefacts.CARD_MODE_DISPATCH if executor == EXECUTOR_TASK \
        else _artefacts.CARD_MODE_PASTE

# inside resolve_phase(...), appended to the returned ResolvedPhase:
step = meta.get("impl_step") or 1 if phase_id == "build" else None
card_mode = _card_mode(executor)
card_path = str(_artefacts.card_path(ticket, phase_id, step))

# core/skills/autorunner.py — the mode is READ, never chosen here (C-001)
def _card_path(ticket: str, phase_id: str) -> Path:
    meta = _lc.read_meta(ticket)
    resolved = _phase_resolver.resolve_phase(
        ticket, phase_id, executor=_phase_resolver.EXECUTOR_HEADLESS)
    return _artefacts.write_prompt_card(ticket, phase_id, meta, mode=resolved.card_mode)
```

## step-5 — Record card bytes and estimated tokens, and print them from `klc next` — DONE

> [!DECISION D-118-6] owner=impl-agent date=2026-09-17T03:30:00Z refs=step-5
> The mandatory pre-ack full-suite run surfaced a real regression this step
> introduced: `render_card()`'s `write_token_metrics` call writes into
> `meta.json` (a TRACKED file), and `next.py` originally called it AFTER its
> `state_tx` block had already committed and CAS-pushed — leaving an
> uncommitted local change that wedged the tree for the next transaction's
> pre-pull stale-guard (`test_klc057_hardening.py::test_soak_ten_mixed_ops_never_wedge_the_tree`
> and `test_klc057_fuzz_concurrent.py::test_scenario3_force_vs_peer_held` both
> failed with this symptom). Fixed by moving the `render_card()` call INSIDE
> `next.py`'s `state_tx` body so its meta.json write rides the same
> glob-commit + CAS-push as the phase advance. Re-verified both tests green
> and the full suite passes (rc=0) via `test_klc105_no_regression.py`'s
> unfiltered subprocess re-run. See `build-log.md` for the full account.

- Goal: every render measures itself into `meta.json:metrics.tokens.<phase>` without ever
  downgrading a provider-sourced record, and `klc next` shows the cost of the card it just wrote.
- RED: `tests/integration/test_klc118_card_metrics.py::test_card_render_records_estimated_tokens_without_downgrading_a_provider_entry`
  and `::test_klc_next_prints_card_bytes_and_estimated_tokens_human_and_json`
  (test-plan rows AC-5 and AC-6) — the first seeds a `source: "provider"` record for `review` plus an
  absent phase, renders, and asserts the provider record is unchanged while the absent phase gains an
  `estimated` record carrying `card_bytes`; the second runs `scripts/klc next` as a subprocess in
  both human and `--json` mode and matches the printed numbers against `Path(card).stat().st_size`
  and `budget_guard.estimate_tokens`.
- GREEN: extend `budget_guard.write_token_metrics` with `card_bytes` and the no-downgrade and
  carry-forward rules; add `render_card()` to `artefacts.py` as the measuring entry point, keeping
  `write_prompt_card` and `write_step_card` as path-returning wrappers; in `core/phases/next.py`
  move the render above the `--json` branch and emit `card`, `card_bytes` and `card_est_tokens`.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc118_card_metrics.py tests/test_budget_guard.py tests/integration/test_verbs_json.py -q`
- Expected: `0 failed`, with both new tests passing
- COMMIT: KLC-118 step-5: record card bytes and estimated tokens and print them from klc next
- Affected: `core/skills/budget_guard.py`, `core/skills/artefacts.py`, `core/phases/next.py`,
  `tests/integration/test_klc118_card_metrics.py` (new).
- Addresses: AC-5, AC-6
- Interfaces: `core/skills/budget_guard.py: write_token_metrics(ticket, phase_id, tokens_in, tokens_out, cache_hit, source="estimated", card_bytes: int | None = None) -> None`;
  `core/skills/artefacts.py: CardRender` (fields `path`, `card_bytes`, `est_tokens`, `degraded`),
  `render_card(ticket: str, phase_id: str, meta: dict, step: int | None = None, mode: str = CARD_MODE_PASTE) -> CardRender`.
- Depends on: step-2, step-3
- Code sketch:

```python
# core/skills/budget_guard.py — inside write_token_metrics, before writing
prior = tokens.get(phase_id) or {}
if prior.get("source") == "provider" and source != "provider":
    return  # never downgrade a provider-sourced record (AC-5)
record = {"in": tokens_in, "out": tokens_out,
          "cache_hit": cache_hit if source == "provider" else 0,
          "source": source}
carried = card_bytes if card_bytes is not None else prior.get("card_bytes")
if carried is not None:
    record["card_bytes"] = carried      # both numbers coexist (Q-003)
tokens[phase_id] = record

# core/skills/artefacts.py
@dataclass
class CardRender:
    path: Path
    card_bytes: int
    est_tokens: int
    degraded: bool

def render_card(ticket, phase_id, meta, step=None, mode=CARD_MODE_PASTE) -> CardRender:
    path, degraded, text = _write_card(ticket, phase_id, meta, step, mode)
    card_bytes = len(text.encode("utf-8"))
    est = _estimate(text)
    _record_card_metrics(ticket, phase_id, card_bytes, est)
    return CardRender(path, card_bytes, est, degraded)

def _record_card_metrics(ticket: str, phase_id: str, card_bytes: int, est: int) -> None:
    try:   # telemetry is non-fatal, exactly as in runner.py
        import budget_guard
        budget_guard.write_token_metrics(ticket, phase_id, est, 0, 0,
                                         source="estimated", card_bytes=card_bytes)
    except Exception:
        pass

# core/phases/next.py — render BEFORE the --json branch, then report both numbers
render = render_card(args.ticket, new_pid, meta, step=step)
if args.json:
    print(json.dumps({"ticket": args.ticket, "phase": new_state,
                      "track": meta.get("track"), "card": str(render.path),
                      "card_bytes": render.card_bytes,
                      "card_est_tokens": render.est_tokens}))
    return 0
print(f"  cat {render.path}")
print(f"    # card: {render.card_bytes} bytes, ~{render.est_tokens} est tokens")
```

## step-6 — Take cards out of the artefact universe and sweep the pre-migration leftovers — DONE

> [!DECISION D-118-4] owner=impl-agent date=2026-09-17T02:30:00Z refs=step-6,F-2,D-2
> Implemented `sweep_legacy_cards(ticket=None, phase_id=None)` — TIGHTER than
> either D-007's original ticket-wide auto-sweep or D-2's own recommended
> ticket-only scope: the automatic call from `render_card` (fired only on a
> NON-degraded/canonical render) passes both `ticket` AND `phase_id`, so it
> can only ever delete the phase currently rendering canonically's own
> stale/legacy ticket-dir copy — never a sibling phase's. F-2's concrete
> failure sequence (phase A degrades to the ticket dir; phase B of the same
> ticket later renders canonically; a ticket-wide sweep would delete A's
> only copy) is covered by a new regression test
> (`test_auto_sweep_is_phase_scoped_and_spares_a_sibling_phases_degraded_card`).
> The bare/global form (`ticket=None`) is reserved for the explicit
> `sweep-cards` CLI subcommand's one-shot operator use, matching D-2's
> recommendation for THAT form specifically.

- Goal: a re-render can no longer dirty the pre-merge snapshot, the retrospective is told cards are
  derived, and stale cards under the ticket tree are deleted without touching the state branch.
- RED: `tests/integration/test_klc118_artefact_universe.py::test_pre_merge_snapshot_excludes_cards_and_retrospective_declares_them_out_of_scope`
  and `tests/integration/test_klc118_card_migration.py::test_migration_sweep_deletes_stale_ticket_dir_cards_and_leaves_the_state_branch_clean`
  (test-plan rows AC-9 and AC-10) — the first asserts `_hash_artefacts` is the identical dict before
  and after a re-render and contains no `_prompt` key, and greps `core/agents/retrospective.md` for
  the new sentence; the second builds a real `git init` worktree with untracked stale cards, runs the
  sweep, and asserts an empty recursive search plus an empty `git status --porcelain`, and that
  `_prompt.md`, `_prompt_step_*.md` and `scratch/` are still in `state_sync._DERIVED_IGNORES` (C-002).
- GREEN: add `sweep_legacy_cards()` and a `sweep-cards` CLI subcommand to `artefacts.py`, called from
  `render_card` whenever the render used the canonical root; add one sentence to
  `core/agents/retrospective.md` declaring prompt cards derived and outside the artefact set, then
  run `python3 core/skills/plugin_gen.py` and commit the regenerated `klc-plugin/agents/retrospective.md`
  (C-004); update the docstring of `tests/integration/test_state_init.py::test_state_init_excludes_derived_from_preserved_commit`
  so its in-ticket `_prompt.md` reads as the pre-migration leftover it now is. `consistency_check.py`
  needs no change — the cards left its tree in step-1.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc118_artefact_universe.py tests/integration/test_klc118_card_migration.py tests/integration/test_state_init.py tests/test_plugin_agents_in_sync.py -q`
- Expected: `0 failed`, with both new tests passing
- COMMIT: KLC-118 step-6: exclude prompt cards from the artefact universe and sweep legacy cards
- Affected: `core/skills/artefacts.py`, `core/agents/retrospective.md`,
  `klc-plugin/agents/retrospective.md` (regenerated),
  `tests/integration/test_klc118_artefact_universe.py` (new),
  `tests/integration/test_klc118_card_migration.py` (new),
  `tests/integration/test_state_init.py`.
- Addresses: AC-9, AC-10
- Interfaces: `core/skills/artefacts.py: sweep_legacy_cards(ticket: str | None = None) -> list[Path]`,
  CLI `python3 core/skills/artefacts.py sweep-cards [KEY]`.
- Depends on: step-1, step-5
- Code sketch:

```python
_LEGACY_CARD_GLOBS = ("**/_prompt.md", "**/_prompt_step_*.md")

def sweep_legacy_cards(ticket: str | None = None) -> list[Path]:
    """Delete prompt cards left under the ticket tree by the pre-KLC-118 layout.
    Pure filesystem deletion: the files were never tracked (FACT F-006), so the
    state branch is untouched and no commit is produced."""
    roots = ([klc_ticket_dir(ticket)] if ticket
             else sorted(p for p in klc_tickets_dir().iterdir() if p.is_dir()))
    removed: list[Path] = []
    for root in roots:
        for pattern in _LEGACY_CARD_GLOBS:
            for stale in root.glob(pattern):
                try:
                    stale.unlink()
                    removed.append(stale)
                except OSError:
                    pass
    return removed
```

The sentence added to the role prompt, which `plugin_gen.py` then mirrors into
`klc-plugin/agents/retrospective.md`:

```text
# core/agents/retrospective.md — the added sentence (AC-9)
Prompt cards (`_prompt.md`, `_prompt_step_N.md`) are DERIVED dispatch scaffolding
rendered outside the ticket directory; they are not part of the artefact set you
read and must never be summarised or cited as ticket history.
```

## step-7 — Gate the size saving and record the measured baseline in the process docs — DONE

> [!DECISION D-118-5] owner=impl-agent date=2026-09-17T03:00:00Z refs=step-7,AC-11
> spec.md's FACT F-003 (81 967 paste bytes / 4 198 dispatch-residue bytes,
> measured on the archived `KLC-102` ticket) is now stale: `KLC-113`
> (prompt hygiene), stacked directly beneath this ticket, shrank several
> `core/agents/*.md` role prompts (removed dead model-switching prose,
> collapsed `{{include:}}` blocks, stripped unexecutable references) AFTER
> F-003 was recorded. Rendering both modes for the same seven phases against
> TODAY's role prompts reproducibly gives **74 346 bytes (paste) / 5 813
> bytes (dispatch), a 92.2 % reduction** — confirmed by rendering the SAME
> real, still-present `.klc/tickets/KLC-102` ticket directly (74 234/5 701,
> matching within the small ticket-name-length delta of the test's own
> fixture ticket). `test_klc118_card_size_regression.py` and
> `docs/process.md` record these reproduced numbers rather than the stale
> spec-time ones, since AC-11's own text only requires the ratio gate and a
> documented baseline that cannot drift from the code — which this satisfies.
> `spec.md` is sealed and keeps FACT F-003 exactly as measured; this is not a
> spec edit, only an acknowledgement that reality moved between design and
> build. The substantive gate (`dispatch_total < 0.10 * paste_total`) holds
> at either figure (5 813/74 346 ≈ 7.8 %; the original 4 198/81 967 ≈ 5.1 %
> — both comfortably under 10 %).

- Goal: the saving this ticket exists for is asserted by a test, and the documented numbers cannot
  drift away from the ones the renderer actually produces.
- RED: `tests/integration/test_klc118_card_size_regression.py::test_dispatch_card_stays_under_ten_percent_of_paste_and_reproduces_the_klc102_baseline`
  (test-plan row AC-11) — render both modes for the seven KLC-102 phases against the real
  `core/agents/*.md` files, assert `dispatch_total < 0.10 * paste_total`, assert `paste_total` within
  5 % of 81 967 bytes, assert `dispatch_total` below an explicit absolute ceiling, and grep
  `docs/process.md` for the recorded figures. Per DECISION D-008 the `dispatch_total` band is an
  absolute ceiling rather than the test plan's ±5 % of 4 198 bytes, because 4 198 is the
  *paste-minus-role-prompt* residue and the dispatch card must additionally carry the pointer block
  AC-1 requires.
- GREEN: add a "Prompt cards" section to `docs/process.md` recording the card root, the two modes,
  both environment variables and the measured baseline (81 967 bytes down to roughly 4 198 bytes of
  ticket-specific residue, a 94.9 % reduction worth about 19 400 estimated tokens per M ticket), and
  fix the stale card-path comment at `config/phases.yml:30`.
- VERIFY: `PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/integration/test_klc118_card_size_regression.py -q && PROJECT_ROOT=/home/ek/projects/klc python3 -m pytest tests/ --ignore=tests/fixtures -q`
- Expected: `1 passed` for the size gate and `0 failed` for the whole suite
- COMMIT: KLC-118 step-7: gate the dispatch/paste size ratio and document the card layout
- Affected: `tests/integration/test_klc118_card_size_regression.py` (new), `docs/process.md`,
  `config/phases.yml`.
- Addresses: AC-11
- Interfaces: none
- Depends on: step-3, step-5, step-6
- Code sketch:

```python
KLC102_PHASES = ("acceptance-test-plan", "design", "discovery",
                 "integrate", "learn", "manual", "review")
PASTE_BASELINE = 81_967      # FACT F-003, measured on KLC-102
DISPATCH_CEILING = 6_000     # residue 4 198 + the AC-1 pointer block, D-008

paste_total = sum(_render_bytes(p, mode=artefacts.CARD_MODE_PASTE) for p in KLC102_PHASES)
dispatch_total = sum(_render_bytes(p, mode=artefacts.CARD_MODE_DISPATCH) for p in KLC102_PHASES)
assert dispatch_total < 0.10 * paste_total       # the AC-11 gate itself
assert abs(paste_total - PASTE_BASELINE) <= 0.05 * PASTE_BASELINE
assert dispatch_total <= DISPATCH_CEILING
doc = (ROOT / "docs" / "process.md").read_text(encoding="utf-8")
for figure in ("81 967", "4 198", "94.9"):
    assert figure in doc
```

## Validation notes

- Seven steps, one logical commit each, dependencies strictly backwards.
- Every behaviour-changing step names a concrete test from `test-plan.md`; no step is
  wiring-only, so none is marked `RED: not applicable`.
- Two steps touch generated plugin artefacts (step-4 through `klc-plugin/skills/run/SKILL.md`,
  step-6 through `core/agents/retrospective.md`); both run `python3 core/skills/plugin_gen.py` and
  commit the regenerated `klc-plugin/` files, as C-004 and the pre-commit hook require.
- No new third-party dependency is introduced at any step (AC-12), and nothing keys off a project's
  programming language (C-005).
- One test-plan amendment is carried by DECISION D-008 and recorded as an add-only addendum in
  `test-plan.md`; no acceptance criterion is weakened, because the AC-11 gate proper is the ten-percent
  ratio.
