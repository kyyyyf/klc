#!/usr/bin/env python3
"""plugin_gen.py — generate klc-plugin/agents/ from core/agents/*.md.

Reads the top-level .md files of core/agents/ that something dispatches (a
phase owns the prompt in phases.yml, or the name is in DISPATCHED_AGENTS),
resolves the model: from the
phase(s) that own it in phases.yml (work.prompt names "core/agents/<file>",
compared after POSIX path normalisation; a prompt with no owner falls back
to stem-then-defaults resolution, KLC-131), and writes the file into the
target agents/ directory with a model: frontmatter block prepended.

Usage:
    python3 core/skills/plugin_gen.py           # writes into klc-plugin/agents/
    from plugin_gen import generate_agents       # callable from tests / klc verb
"""
from __future__ import annotations

import posixpath
import re
import sys
import tempfile
from pathlib import Path

_skills_dir = Path(__file__).resolve().parent
_project_root = _skills_dir.parent.parent
sys.path.insert(0, str(_skills_dir))
sys.path.insert(0, str(_project_root))

import models as _m
import phases as _ph  # noqa: E402  KLC-131: prompt -> owner phase lookup
from core.shared.paths import framework_root  # noqa: E402


# CC plugin model alias map: concrete model ID → CC frontmatter alias.
# A role pointing above Opus works — it will fall back to the full model ID.
_MODEL_TO_CC_ALIAS: dict[str, str] = {
    "claude-opus-5-5":           "opus",   # new
    "claude-opus-4-8":           "opus",
    "claude-opus-4-7":           "opus",   # kept — back-compat
    "claude-opus-4-6":           "opus",
    "claude-sonnet-5":           "sonnet", # new
    "claude-sonnet-4-6":         "sonnet", # kept — back-compat
    "claude-sonnet-4-5":         "sonnet",
    "claude-haiku-4-5-20251001": "haiku",
    "claude-haiku-4-5":          "haiku",
    "claude-haiku-3-5":          "haiku",
    "claude-fable-5":            "fable",
}


def cc_alias(model_id: str) -> str:
    return _MODEL_TO_CC_ALIAS.get(model_id, model_id)


# Back-compat: earlier callers used the private name.
_cc_alias = cc_alias


# ---------------------------------------------------------------------------
# Verb-dictionary (single source for skills + shared command descriptions).
#
# `VERB_SPECS` holds the {short, use_when} strings for the 6 PASSTHROUGH verbs.
# The strings are lifted VERBATIM from the current committed
# `klc-plugin/skills/<verb>/SKILL.md` (constraint C-003 — the generator
# reproduces the delivery layer byte-for-byte, it does not "improve" it).
#
# Three verb sets are kept DISTINCT because they genuinely differ:
#   * SKILL_VERBS    — skills are generated for exactly these (== VERB_SPECS).
#   * BESPOKE_SKILLS — handwritten skills (discuss-feature); never
#     generated, only presence-guarded (constraint C-001: no Python driver).
#   * command verbs  — `_LIFECYCLE_CMDS` (== VERB_SPECS). `step verify` and
#     `publish` stay CLI-only (KLC-180): no command stub, no skill.
# ---------------------------------------------------------------------------
_GO_AFTER = """\

## Driving a ticket to integrate (`klc go <KEY> --until integrate`)

You are the main agent. `klc go` decides every move; you only dispatch phase
agents and ask the human. This one skill is the whole orchestrator loop.

1. Run `klc go <KEY> --until integrate`. Exit 0: the ticket reached
   `integrate:work`. Tell the human: merge the branch per the project's rules,
   then run `klc go <KEY> --pick 1`, then run `klc go` again for the remaining
   phases; stop. Exit 1: show stderr verbatim and stop.
2. Exit 2: the stop line carries exactly ONE reason. Check them in this order.
   - **Guardrail** (`integrate`, `cap`, `budget-ceiling`): STOP, show the line verbatim.
   - **Clarify** (`clarify needed`): go to step 3a.
   - **Pick** (`klc go <KEY> --pick N`): STOP and ask the human, with the options
     shown. Never guess a pick. For an advisory stop, read
     `<ticket-dir>/advisories.json`, report the phase's `high` and `medium`
     records plus a bare count of the rest; never parse the phase-history note.
   - **Build not green** (`build is not green`): go to step 3 with phase `build`.
   - **Agent card** (`<phase>:work needs the agent`): go to step 3.
   - Anything else: STOP, show the line verbatim.
3. Dispatch the phase agent.
   a. **Clarify gate** (the `clarify needed` stop; phase `intake`, `meta.json:clarify_required` true):
      follow `core/agents/intake-triage.md` "Interactive clarify (main-loop
      only)" now: ask via `AskUserQuestion` per
      `clarify_config.load_clarify_style()`, write the answers into `raw.md`,
      re-run `route_heuristic.classify()`, clear `clarify_required`, run
      `klc go <KEY> --pick 1`, then go to step 1. Never dispatch discovery in the same breath.
   b. Resolve: `core.skills.phase_resolver.resolve_phase(<KEY>, phase_id,
      executor="task")` gives `runs_inline`, `agent_type`, `card_mode`. The mode
      is decided there and nowhere else. An agent stop of `klc go` also prints
      one line `dispatch: agent=<klc-…> model=<alias> card=<path>`; its `model` is
      the models.yml role for the ticket's TRACK and is the one you pass below.
   c. Unless inline, re-render the card with `core.skills.artefacts.render_card(
      <KEY>, phase_id, meta, step=<build only>, mode=resolved.card_mode)`
      (`klc go` wrote a stale paste card). Show the warn-only
      `core.skills.budget_guard.real_spend_warning(track, ticket=<KEY>)` line, if any.
   d. If `resolved.runs_inline` (XS): do the work yourself and end with the
      completion-signal JSON. Otherwise
      `Task(subagent_type=<agent>, model=<model>, prompt=<card text>)` with the
      `agent` and `model` of the `dispatch:` line (never omit `model=`: the
      agent file's frontmatter `model:` is not relied on), then `core.skills.run_signal.record_signal_tokens`.
   e. Parse with `core.skills.run_signal.parse_signal(result, expected_phase=
      phase_id)`. `None` is a failure: retry the same phase once
      (`should_retry`); on the second failure STOP and show the raw result.
   f. Non-empty `blocking_questions`: STOP and show them unchanged.
   g. Build only: run `klc step verify <KEY> N` for each step missing or stale in
      `build/steps.json` and report failures verbatim (not after a retry).
   h. Review: the agent gets `--diff recorded` and plans three layers. If the
      plan refuses over the cap, STOP; never pass `--over-cap` yourself.
4. Go to step 1 (`klc go` acks the finished phase).

Rules: never merge and never push (`integrate:work` is where the human merges);
every reviewer is a fresh subagent (not a fork) and may not write to git; never
guess a pick, invent an answer, or skip the clarify pass.
"""

VERB_SPECS: dict[str, dict[str, str]] = {
    "intake": {
        "short": "Create a new klc ticket and start the lifecycle",
        "use_when": "Use when the user wants to create or start a new klc ticket from a description.",
    },
    "status": {
        "short": "Show current phase and track for a ticket",
        "use_when": "Use when the user wants to check what phase or track a klc ticket is in.",
    },
    "go": {
        "short": "Move the ticket one step forward, or until a phase",
        "use_when": "Use when the user wants to advance a klc ticket.",
        "allowed_tools": "Bash, Task, AskUserQuestion",
        "after": _GO_AFTER,
    },
    "back": {
        "short": "Return the ticket to an earlier phase with a reason",
        "use_when": "Use when the user wants to redo an earlier phase of a klc ticket.",
    },
    "fix": {
        "short": "Correct a ticket's meta field with an audited record",
        "use_when": "Use when the user wants to change a klc ticket's track, modules, risk tags, kind, epic or blockers.",
        "operator_only": "true",
    },
    "doctor": {
        "short": "Check install health, bootstrap a project or refresh the index",
        "use_when": "Use when the user wants to check klc health, set klc up in a project or refresh the code index.",
        "argument_hint": "[--install <root>] [--index]",
        "operator_only": "true",
        "args_note": "Pass any options straight through; surface the CLI's check, install and index output, including any advisory or blocking lines, to the user.",
    },
}

SKILL_VERBS: set[str] = set(VERB_SPECS)
BESPOKE_SKILLS: set[str] = {"discuss-feature"}

# Optional per-verb keys in VERB_SPECS (everything else is the fixed template):
#   argument_hint  - overrides the default `<TICKET-ID> [options]` (skill AND command stub)
#   operator_only  - "true" adds `disable-model-invocation: true` to the skill frontmatter:
#                    the verb changes audited state (`fix`) or bootstraps a repo (`doctor
#                    --install`), so the model must never run it on its own initiative.
#                    The command stub stays: a human typing /klc:<verb> is the intended path.
#   allowed_tools  - overrides the default `Bash` (skill AND command stub); `go` also
#                    dispatches phase agents (Task) and asks the human (AskUserQuestion)
#   after          - markdown appended to the skill body (the instructions the model
#                    follows after the CLI call); the `run` loop now lives in `go`
#   args_note      - replaces the default "Pass the ticket key and any options ..." sentence
_DEFAULT_HINT = "<TICKET-ID> [options]"
_DEFAULT_ARGS_NOTE = (
    "Pass the ticket key and any options straight through; surface\n"
    "the CLI's phase/gate output, including any advisory or blocking lines, to the user.\n"
)

# The fixed passthrough SKILL.md template. {v}, {short}, {use_when}, {hint}, {extra}
# and {note} vary.
_SKILL_TMPL = (
    "---\n"
    "name: klc-{v}\n"
    "description: {short}. {use_when}\n"
    "argument-hint: {hint}\n"
    "{extra}"
    "allowed-tools: {tools}\n"
    "---\n"
    "\n"
    "# /klc:{v} — {short}\n"
    "\n"
    "Run `klc {v} $ARGUMENTS` via Bash and show the result verbatim. This is a thin\n"
    "adapter over the `klc` CLI (the plugin shells out to the existing binary — no logic\n"
    "is reimplemented here). {note}{after}"
)


def _hint(v: str) -> str:
    return VERB_SPECS[v].get("argument_hint", _DEFAULT_HINT)


def _render_skill(v: str) -> str:
    spec = VERB_SPECS[v]
    extra = "disable-model-invocation: true\n" if spec.get("operator_only") == "true" else ""
    note = spec["args_note"] + "\n" if "args_note" in spec else _DEFAULT_ARGS_NOTE
    return _SKILL_TMPL.format(v=v, short=spec["short"], use_when=spec["use_when"],
                              hint=_hint(v), extra=extra, note=note,
                              tools=spec.get("allowed_tools", "Bash"),
                              after=spec.get("after", ""))


def generate_skills(output_dir: Path | None = None) -> list[Path]:
    """Generate the passthrough ``skills/<verb>/SKILL.md`` for each SKILL_VERBS
    verb, byte-exact to the committed delivery layer (C-003).

    Only SKILL_VERBS are emitted, so no ``skills/publish`` is produced and the
    bespoke skills (run, discuss-feature) are never overwritten (AC-3).

    Args:
        output_dir: Destination ``skills/`` directory. Defaults to
                    ``<fw_root>/klc-plugin/skills/``.

    Returns:
        List of generated ``SKILL.md`` paths.
    """
    if output_dir is None:
        output_dir = framework_root() / "klc-plugin" / "skills"
    written: list[Path] = []
    for v in sorted(SKILL_VERBS):
        d = output_dir / v
        d.mkdir(parents=True, exist_ok=True)
        spec = VERB_SPECS[v]
        dest = d / "SKILL.md"
        dest.write_text(_render_skill(v), encoding="utf-8")
        written.append(dest)
    return written


# The static plugin manifest, lifted VERBATIM from the committed
# `klc-plugin/.claude-plugin/plugin.json` (C-003) — trailing newline included —
# so the manifest is regenerable, not handwritten-and-lost.
_MANIFEST = (
    "{\n"
    '  "name": "klc",\n'
    '  "displayName": "klc — ticket lifecycle",\n'
    '  "version": "0.2.0",\n'
    '  "description": "Thin adapter that wraps the klc CLI as native Claude Code slash commands, subagents, and skills. Drives a ticket through its lifecycle (intake → discovery → build → review → integrate → archive) with TDD-ordered, track-scaled gates. No MCP server — shells out to the klc binary via Bash.",\n'
    '  "keywords": ["klc", "ticket", "lifecycle", "tdd", "workflow", "orchestration"]\n'
    "}\n"
)


def generate_manifest(output_dir: Path | None = None) -> Path:
    """Write ``.claude-plugin/plugin.json`` from the ``_MANIFEST`` constant,
    byte-exact to the committed manifest (AC-2 / C-003).

    Args:
        output_dir: Destination ``.claude-plugin/`` directory. Defaults to
                    ``<fw_root>/klc-plugin/.claude-plugin/``.

    Returns:
        Path to the written ``plugin.json``.
    """
    if output_dir is None:
        output_dir = framework_root() / "klc-plugin" / ".claude-plugin"
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "plugin.json"
    dest.write_text(_MANIFEST, encoding="utf-8")
    return dest


# Line-anchored, non-recursive {{include:<name>}} directive (KLC-113, D-001).
# Anchored to a whole line so a prose mention of the syntax is never expanded
# (KLC-104 lesson: an unanchored marker regex matches the marker's own
# description in prose).
_INCLUDE_RE = re.compile(r"(?m)^[ \t]*\{\{include:([a-z0-9][a-z0-9\-]*)\}\}[ \t]*$")


def expand_includes(text: str, includes_dir: Path | None = None) -> str:
    """Substitute each line-anchored ``{{include:name}}`` directive with the body
    of ``<includes_dir>/<name>.md``. Non-recursive by design: a directive inside
    an include body is left as literal text (KLC-113, D-001) — this is a single
    substitution pass, not a template engine.

    Args:
        text: the source prompt text, before frontmatter is prepended.
        includes_dir: directory holding the include bodies. Defaults to
                      ``<fw_root>/core/agents/_includes``.

    Returns:
        *text* with every directive replaced by its include's body.

    Raises:
        ValueError: an unresolvable include name — raising loudly here is the
                    point; a missing include must never ship as a literal
                    directive string in a dispatched prompt.
    """
    if includes_dir is None:
        includes_dir = framework_root() / "core" / "agents" / "_includes"

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        src = includes_dir / f"{name}.md"
        if not src.exists():
            raise ValueError(
                f"plugin_gen: unknown include {name!r} (no such file: {src})"
            )
        return src.read_text(encoding="utf-8").rstrip("\n")

    return _INCLUDE_RE.sub(_sub, text)


def _resolve_model_id(mc: "_m.Models", keys: list[str]) -> str:
    """Model id for a prompt resolved through *keys* (its owner phases in
    phases.yml order, or ``[stem]`` for an unowned prompt).

    KLC-131 AC-3: several owners -> the role with the highest rank; a rank
    tie keeps the earliest key (max returns the first maximal item), so the
    choice follows phases.yml order, never dict or glob order.

    An owner/stem with no ``phase_roles`` entry does not raise —
    ``Models.resolve()`` returns a ``ResolvedModel`` built from ``defaults``
    without error, and it is scored at ``defaults.rank``/``defaults.model``
    below because ``"defaults"`` is never a key under ``roles:``
    (``mc.roles.get(resolved.role)`` returns ``None``). The ``except``
    clause only catches a role that fails ``Models.resolve()`` outright
    (e.g. an unknown provider) — review LOW: same fallback either way, but
    reached through a different branch (findings.json, kind code-review).
    """
    candidates: list[tuple[int, str]] = []
    for key in keys:
        try:
            resolved = mc.resolve(key)
        except (KeyError, ValueError):
            candidates.append((mc.defaults.rank, mc.defaults.model))
            continue
        role = mc.roles.get(resolved.role)
        rank = role.rank if role is not None else mc.defaults.rank
        candidates.append((rank, resolved.model))
    return max(candidates, key=lambda c: c[0])[1]


def _owns_prompt(phase_prompt: str, agent_name: str) -> bool:
    """True when *phase_prompt* (a phase's ``work.prompt``) names the same
    file as ``core/agents/<agent_name>``, after POSIX path normalisation.

    KLC-131 review-fix (AC-1, external review LOW): a non-canonical but
    otherwise valid ``work.prompt`` such as ``./core/agents/impl.md`` passes
    ``validate_config`` (the file exists) and ``phase_resolver`` already
    recognises it via ``Path(phase.prompt).stem``. An exact-string compare
    here would silently miss it and fall back to the stem — normalising
    both sides with ``posixpath.normpath`` keeps them in agreement. An
    empty ``work.prompt`` (an intentionally unowned phase) never matches.
    """
    if not phase_prompt:
        return False
    return (
        posixpath.normpath(phase_prompt)
        == posixpath.normpath(f"core/agents/{agent_name}")
    )


# Agents dispatched outside any phase (ReviewKind judges, intake triage, the
# external reviewer). A phase-owned prompt is read from phases.yml at generation
# time; these six have no phase, so they are named here. Anything else in
# core/agents/ has no plugin copy (KLC-180).
DISPATCHED_AGENTS: frozenset[str] = frozenset({
    "intake-triage", "spec-reviewer", "test-plan-reviewer",
    "impl-plan-reviewer", "drift-reviewer", "external-review",
})


def plugin_agent_names(phase_prompts: list[str]) -> set[str]:
    """Stems of the agents the plugin ships: the prompt of every phase plus
    DISPATCHED_AGENTS. An empty prompt (a phase with no agent) is skipped."""
    owned = {posixpath.basename(p)[:-3] for p in phase_prompts if p}
    return owned | set(DISPATCHED_AGENTS)


def generate_agents(
    output_dir: Path | None = None,
    *,
    models_yml: Path | None = None,
) -> list[Path]:
    """Generate plugin agents from core/agents/*.md.

    Args:
        output_dir:  Destination directory. Defaults to
                     <fw_root>/klc-plugin/agents/.
        models_yml:  Override models.yml path (for testing). When set, the
                     models cache is reset and loaded from this file.

    Returns:
        List of generated file paths.
    """
    fw = framework_root()
    if output_dir is None:
        output_dir = fw / "klc-plugin" / "agents"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load models — optionally override yml path.
    if models_yml is not None:
        # Temporarily redirect the load path by monkey-patching _load_path.
        _m._reset_cache()
        orig_load_path = _m._load_path

        def _patched_load_path() -> Path:
            return models_yml

        _m._load_path = _patched_load_path
        try:
            mc = _m.load_models(force=True)
        finally:
            _m._load_path = orig_load_path
            _m._reset_cache()
    else:
        mc = _m.load_models()

    # KLC-131 (AC-8): read phases.yml through load_phases() so its own
    # validations apply; a missing or invalid file raises here, before any
    # agent is written — never a silent stem-only fallback.
    phases_model = _ph.load_phases(force=True)

    agents_src = fw / "core" / "agents"
    generated: list[Path] = []
    wanted = plugin_agent_names([p.prompt for p in phases_model.ordered])

    # Remove plugin copies of agents that no longer ship (KLC-180).
    for old in output_dir.glob("*.md"):
        if old.stem not in wanted:
            old.unlink()

    for src in sorted(agents_src.glob("*.md")):
        if src.stem not in wanted:
            continue
        phase_id = src.stem  # agent identity: name/description stay stem-based
        # KLC-131 (AC-1): resolve model from the phase(s) that own this
        # prompt (Phase.prompt == "core/agents/<file>"); a prompt no phase
        # owns keeps today's stem-then-defaults resolution (AC-2).
        owners = [
            p.id for p in phases_model.ordered
            if _owns_prompt(p.prompt, src.name)
        ]
        cc_model = _cc_alias(_resolve_model_id(mc, owners or [phase_id]))

        # Build frontmatter.
        fm_lines = [
            "---",
            f"name: klc-{phase_id}",
            f"description: klc {phase_id} phase agent",
            f"model: {cc_model}",
            "---",
            "",
        ]
        frontmatter = "\n".join(fm_lines)

        dest = output_dir / src.name
        original = expand_includes(src.read_text(encoding="utf-8"))
        dest.write_text(frontmatter + original, encoding="utf-8")
        generated.append(dest)

    return generated


_LIFECYCLE_CMDS = ("intake", "status", "go", "back", "fix", "doctor")


# Command-only verbs (∉ VERB_SPECS): none since KLC-180 (`publish` is CLI-only).
# Shared verbs read their description from VERB_SPECS[verb]["short"]
# (AC-4 single source), so reconciling VERB_SPECS also reconciles the command.
_COMMAND_ONLY_DESC: dict[str, str] = {}


def _cmd_desc(verb: str) -> str:
    """Description for a command stub. Shared verbs are single-sourced from
    ``VERB_SPECS[verb]["short"]`` (AC-4); command-only verbs keep their own."""
    if verb in VERB_SPECS:
        return VERB_SPECS[verb]["short"]
    return _COMMAND_ONLY_DESC.get(verb, f"Run klc {verb}")


def _generate_commands(output_dir: Path) -> list[Path]:
    """Write static command stubs (idempotent — skips existing files)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    for verb in _LIFECYCLE_CMDS:
        dest = output_dir / f"{verb}.md"
        if dest.exists():
            generated.append(dest)
            continue
        desc = _cmd_desc(verb)
        body = f"Run `klc {verb} $ARGUMENTS` via Bash and show the result.\n"
        if VERB_SPECS.get(verb, {}).get("after"):
            # `go` must reach the dispatch loop from the slash command itself.
            body = (
                "Run `klc go <KEY> --until integrate` for the ticket named in `$ARGUMENTS`\n"
                "(keep any explicit option such as `--pick N`, `--until`, `--dry-run` as given),\n"
                "then follow the dispatch loop below.\n"
                + VERB_SPECS[verb]["after"]
            )
        content = (
            f"---\n"
            f"description: {desc}\n"
            f"argument-hint: {_hint(verb) if verb in VERB_SPECS else _DEFAULT_HINT}\n"
            f"allowed-tools: [{VERB_SPECS.get(verb, {}).get('allowed_tools', 'Bash')}]\n"
            f"---\n\n"
            f"{body}"
        )
        dest.write_text(content, encoding="utf-8")
        generated.append(dest)

    # Command stubs of retired verbs (run, step, publish, ...) are removed.
    for old in output_dir.glob("*.md"):
        if old.stem not in _LIFECYCLE_CMDS:
            old.unlink()

    return generated


# Staged-path prefixes/names that make the plugin drift-check in scope (AC-8).
_PLUGIN_SOURCE_AGENTS_PREFIX = "core/agents/"
_PLUGIN_SOURCE_GEN = "core/skills/plugin_gen.py"
# KLC-131 review-fix (external MEDIUM): both are now generate_agents() inputs
# for model: resolution — phases.yml supplies prompt ownership (AC-1/AC-3),
# models.yml supplies phase_roles — so staging either alone must also put the
# drift gate in scope, not only a core/agents/* prompt or plugin_gen.py itself.
_PLUGIN_SOURCE_PHASES_YML = "config/phases.yml"
_PLUGIN_SOURCE_MODELS_YML = "config/models.yml"


def plugin_sources_staged(staged_paths: list[str]) -> bool:
    """True when the staged paths include a plugin SOURCE — a
    ``core/agents/*`` prompt, ``core/skills/plugin_gen.py`` (the
    verb-dictionary lives there), or either ``config/phases.yml`` /
    ``config/models.yml`` (KLC-131: both now feed ``generate_agents()``'s
    model: resolution). Scopes the pre-commit gate (AC-8) so it never fires
    for an unrelated commit. Injectable for unit testing."""
    for p in staged_paths:
        if (
            p.startswith(_PLUGIN_SOURCE_AGENTS_PREFIX)
            or p in (
                _PLUGIN_SOURCE_GEN,
                _PLUGIN_SOURCE_PHASES_YML,
                _PLUGIN_SOURCE_MODELS_YML,
            )
        ):
            return True
    return False


def _stub_description(md: Path) -> str | None:
    """The ``description:`` frontmatter value of a command stub, or ``None`` when
    no such line exists. Used by the CMD-DESC-DRIFT check (review LOW-2)."""
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return None


def check_sync(committed_root: Path | None = None) -> list[str]:
    """Regenerate agents+skills+manifest into a throwaway temp dir and compare
    to the committed plugin tree, returning drift findings (AC-7).

    Read-only: it never writes to *committed_root* and never stages anything.
    *committed_root* is injectable (defaults to ``<fw_root>/klc-plugin``) so a
    mutated committed tree is testable (review F-2).

    Each finding is ``MISSING: <rel>`` (no committed copy), ``DRIFT: <rel>``
    (committed bytes differ from the regenerated bytes), or
    ``STALE: agents/<file>`` (a committed agent file the generator does not
    produce), ``CMD-DESC-DRIFT: commands/<verb>.md`` (a shared verb's committed command
    stub description no longer equals ``VERB_SPECS[verb]["short"]`` — review
    LOW-2; ``CMD-TOOLS-DRIFT: commands/<verb>.md`` is the same for the
    ``allowed-tools`` line; command stubs are skip-if-exists so we ASSERT the description, we do
    not byte-regenerate them, D-001).
    """
    if committed_root is None:
        committed_root = framework_root() / "klc-plugin"
    findings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        generate_agents(output_dir=t / "agents")
        generate_skills(output_dir=t / "skills")
        generate_manifest(output_dir=t / ".claude-plugin")

        # agents — byte-exact
        for gen in sorted((t / "agents").glob("*.md")):
            dst = committed_root / "agents" / gen.name
            rel = f"agents/{gen.name}"
            if not dst.exists():
                findings.append(f"MISSING: {rel}")
            elif dst.read_bytes() != gen.read_bytes():
                findings.append(f"DRIFT: {rel}")

        # stale agents — a committed agent file the generator no longer emits
        # (KLC-180: only phase-owned and DISPATCHED_AGENTS prompts ship).
        generated_names = {g.name for g in (t / "agents").glob("*.md")}
        agents_dir = committed_root / "agents"
        if agents_dir.is_dir():
            for f in sorted(agents_dir.glob("*.md")):
                if f.name not in generated_names:
                    findings.append(f"STALE: agents/{f.name}")

        # skills — byte-exact (SKILL_VERBS only)
        for v in sorted(SKILL_VERBS):
            gen = t / "skills" / v / "SKILL.md"
            dst = committed_root / "skills" / v / "SKILL.md"
            rel = f"skills/{v}/SKILL.md"
            if not dst.exists():
                findings.append(f"MISSING: {rel}")
            elif dst.read_bytes() != gen.read_bytes():
                findings.append(f"DRIFT: {rel}")

        # manifest — byte-exact
        gen = t / ".claude-plugin" / "plugin.json"
        dst = committed_root / ".claude-plugin" / "plugin.json"
        rel = ".claude-plugin/plugin.json"
        if not dst.exists():
            findings.append(f"MISSING: {rel}")
        elif dst.read_bytes() != gen.read_bytes():
            findings.append(f"DRIFT: {rel}")

    # command-description drift — a shared verb (∈ SKILL_VERBS) whose committed
    # commands/<verb>.md exists but whose description no longer matches the
    # single source VERB_SPECS[verb]["short"] (review LOW-2). Bring the offline
    # drift-guard assertion into the commit-time gate. We assert equality only
    # (no byte regeneration of command stubs — D-001).
    for v in sorted(SKILL_VERBS):
        cmd = committed_root / "commands" / f"{v}.md"
        if not cmd.exists():
            continue
        if _stub_description(cmd) != VERB_SPECS[v]["short"]:
            findings.append(f"CMD-DESC-DRIFT: commands/{v}.md")
        want = f"allowed-tools: [{VERB_SPECS[v].get('allowed_tools', 'Bash')}]"
        if want not in cmd.read_text(encoding="utf-8").splitlines():
            findings.append(f"CMD-TOOLS-DRIFT: commands/{v}.md")

    # stale stubs — a command stub whose verb the generator no longer emits
    # (KLC-177: next/ack/ship/jump/abort were removed). skip-if-exists would keep
    # them forever, so the check is what notices the leftover file.
    known = set(_LIFECYCLE_CMDS)
    cmd_dir = committed_root / "commands"
    if cmd_dir.is_dir():
        for cmd in sorted(cmd_dir.glob("*.md")):
            if cmd.stem not in known:
                findings.append(f"STALE: commands/{cmd.name}")

    return findings


def _staged_paths() -> list[str]:
    """Paths staged for the current commit (``git diff --cached --name-only``),
    filtered to added/copied/modified. An injectable seam so ``--check-if-staged``
    is unit-testable without a real index (review LOW-1). Runs in the process
    cwd — i.e. the repo the pre-commit hook is firing in."""
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line for line in out.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    argv = [] if argv is None else argv

    if "--check" in argv:
        findings = check_sync()
        if findings:
            print("plugin drift detected — the committed plugin is stale:")
            for f in findings:
                print(f"  {f}")
            print("run: python3 core/skills/plugin_gen.py")
            return 1
        return 0

    if "--check-if-staged" in argv:
        # The REAL hook gate (review LOW-1): scope with the same predicate the
        # tests exercise, so the hook and the unit test share one definition of
        # "in scope" — no grep re-implementation in bash.
        staged = _staged_paths()
        if not plugin_sources_staged(staged):
            return 0  # no plugin source staged — nothing to check
        findings = check_sync()
        if findings:
            print("plugin drift detected — the committed plugin is stale:")
            for f in findings:
                print(f"  {f}")
            print("run: python3 core/skills/plugin_gen.py")
            return 1
        return 0

    fw = framework_root()
    plugin_dir = fw / "klc-plugin"
    agents_out = plugin_dir / "agents"
    commands_out = plugin_dir / "commands"
    skills_out = plugin_dir / "skills"

    generated_agents = generate_agents(output_dir=agents_out)
    print(f"Generated {len(generated_agents)} agent files in {agents_out}")

    generated_cmds = _generate_commands(output_dir=commands_out)
    print(f"Generated/verified {len(generated_cmds)} command files in {commands_out}")

    generated_skills = generate_skills(output_dir=skills_out)
    print(f"Generated {len(generated_skills)} skill files in {skills_out}")

    manifest = generate_manifest(output_dir=plugin_dir / ".claude-plugin")
    print(f"Generated manifest {manifest}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
