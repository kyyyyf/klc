"""Prompt-structural tests for KLC-091 (E-04 · design enrichment, the SA layer).

E-04 is a PROMPT-layer ticket: it enriches the single phase-3 orchestrating
prompt `core/agents/design.md` so the design agent produces, in its existing
artifacts, the SA realization of the finalized SAOC spec — data models, API
contracts, error handling & idempotency, decision tables for combinatoric ACs,
and a `## Design invariants (spine)` section (Binds / Prevents / Rule). There is
no new runtime code, so the acceptance signal is a set of prompt-structural
assertions.

Every added prose claim is pinned to a REAL structural marker or an existing
tool entry point — the epic's recurring failure class (083/084/085/088/090) was
prompt prose promising a capability the code did not back. `test_no_fabricated_
tool_in_design` is the closed-world guard: it mirrors E-03's AC-7 /
`plan_quality.unresolved_api_refs` shape and fails on any fabricated skill / CLI
reference (there is NO `core/skills/spine*.py` — the spine framing is pure
prose/structure).
"""
from __future__ import annotations

import importlib
import re
import sys

from tests.prompt_harness import _FW_ROOT

_AGENTS = _FW_ROOT / "core" / "agents"
_DESIGN = _AGENTS / "design.md"
_SKILLS = _FW_ROOT / "core" / "skills"
_PLUGIN_DESIGN = _FW_ROOT / "klc-plugin" / "agents" / "design.md"


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# step-1 — data models + API contracts + error handling & idempotency
# ---------------------------------------------------------------------------

def test_design_instructs_data_models():
    """AC-1: design.md instructs a DATA MODELS deliverable carrying all five
    facets — entities, fields, relationships, identity/uniqueness, and
    lifecycle / state transitions."""
    low = _read(_DESIGN).lower()
    assert "data model" in low, "design.md must name a data-model deliverable"
    for facet in ("entit", "fields", "relationship"):
        assert facet in low, f"data-model deliverable must cover '{facet}'"
    assert "identity" in low and "uniqueness" in low, (
        "data-model deliverable must cover identity / uniqueness"
    )
    assert "lifecycle" in low and "state transition" in low, (
        "data-model deliverable must cover lifecycle / state transitions"
    )


def test_design_instructs_api_contracts():
    """AC-2: design.md instructs an API CONTRACTS deliverable — the
    interfaces / signatures the change exposes or calls — with symbols verified
    via LSP."""
    text = _read(_DESIGN)
    low = text.lower()
    assert "api contract" in low, "design.md must name an API-contract deliverable"
    assert "interface" in low and "signature" in low, (
        "API-contract deliverable must name interfaces / signatures"
    )
    assert "expose" in low and "call" in low, (
        "API-contract deliverable must cover interfaces the change exposes or calls"
    )
    assert "lsp" in low, "API-contract symbols must be verified via LSP"


def test_design_instructs_error_handling_idempotency():
    """AC-3: design.md instructs an ERROR HANDLING & IDEMPOTENCY deliverable —
    failure modes, retries, idempotency keys, and at-least-once / at-most-once
    delivery semantics."""
    low = _read(_DESIGN).lower()
    assert "error handling" in low and "idempoten" in low, (
        "design.md must name an error-handling-and-idempotency deliverable"
    )
    assert "failure mode" in low, "must cover failure modes"
    assert "retr" in low, "must cover retries"
    assert "idempotency key" in low, "must cover idempotency keys"
    assert "at-least-once" in low and "at-most-once" in low, (
        "must cover at-least-once / at-most-once delivery semantics"
    )


# ---------------------------------------------------------------------------
# step-2 — decision tables for combinatoric ACs + spine invariants
# ---------------------------------------------------------------------------

def test_design_instructs_decision_tables():
    """AC-4: design.md instructs a DECISION TABLE for each combinatoric AC —
    input combinations mapped to the expected outcome — making testability of
    combinatoric ACs explicit (each row a candidate test row)."""
    text = _read(_DESIGN)
    low = text.lower()
    assert "decision table" in low, "design.md must name a decision-table deliverable"
    assert "combinatoric" in low, "decision tables must be tied to combinatoric ACs"
    assert "combination" in low, "decision table maps input combinations"
    assert "expected outcome" in low, (
        "decision table's last column is the expected outcome"
    )
    assert "test" in low, "each decision-table row is a candidate test row"


def test_design_records_spine_invariants():
    """AC-5: design.md records each durable design decision as a spine invariant
    block carrying Binds / Prevents / Rule, stating the DECISION and not its
    rationale, cross-linked to its existing `D-NNN` item."""
    text = _read(_DESIGN)
    low = text.lower()
    assert "## Design invariants (spine)" in text, (
        "design.md must instruct a `## Design invariants (spine)` section"
    )
    # the section is recorded in the existing options.md artifact (C-005: no new artifact)
    assert "options.md" in text, "spine invariants go into the existing options.md"
    # all three invariant fields
    for field in ("Binds", "Prevents", "Rule"):
        assert field in text, f"spine invariant block must carry the {field} field"
    # decision, not rationale
    assert "rationale" in low and (
        "not its rationale" in low or "not the rationale" in low or "not rationale" in low
    ), "spine records the DECISION, not its rationale"
    # cross-linked to the existing D-NNN item (reuses items.py, no new artifact)
    assert "D-NNN" in text, "each invariant must cross-link to its D-NNN DECISION item"


# ---------------------------------------------------------------------------
# step-3 — SA/BA separation + plugin parity + closed-world honesty roll-up
# ---------------------------------------------------------------------------

def test_design_states_sa_ba_separation():
    """AC-6: design.md states the SA/BA separation — the design phase CONSUMES
    the finalized SAOC spec and does NOT re-elicit requirements, and routes a
    self-found requirements gap BACK (a QUESTION / marker) rather than authoring
    the intent itself."""
    text = _read(_DESIGN)
    low = text.lower()
    # SA consumes, does not re-elicit
    assert "sa layer" in low and "ba layer" in low, (
        "design.md must frame the SA-vs-BA layer separation"
    )
    assert "consume" in low, "design (SA) must state it CONSUMES the finalized spec"
    assert "re-elicit" in low or "re-open" in low, (
        "design (SA) must state it does not re-elicit / re-open requirements"
    )
    # route a self-found gap back, don't author intent
    assert "[!QUESTION]" in text, "a self-found gap is routed back as a [!QUESTION]"
    assert "route" in low and "back" in low, "a self-found gap is routed BACK"
    assert "author" in low, "design must NOT author the missing intent itself"


def test_plugin_design_in_sync(tmp_path):
    """AC-7 (C-003): the deployed `klc-plugin/agents/design.md` equals what
    `plugin_gen.generate_agents` produces from the enriched core source (body +
    generated frontmatter). `phase_resolver` serves the PLUGIN copy, so a stale
    copy means the enrichment never runs.

    Scope is `design.md` ONLY — NOT the `design*.md` glob. E-04 edits only the
    SOURCE of `core/agents/design.md`; `design-scout.md`'s source is unchanged, so
    its stale plugin copy is pre-existing drift owned by KLC-092 (the dedicated
    plugin-sync ticket that regenerates ALL agents). Do NOT loop `design*.md` here:
    committing `klc-plugin/agents/design-scout.md` on this branch would overlap
    KLC-092's turf. Assert on the single `design.md` file only."""
    sys.path.insert(0, str(_SKILLS))
    from plugin_gen import generate_agents

    # generate_agents writes every agent into tmp_path; we deliberately read back
    # ONLY design.md — design-scout and the rest are KLC-092's, not E-04's.
    generate_agents(output_dir=tmp_path)
    expected = (tmp_path / "design.md").read_text(encoding="utf-8")
    committed = _PLUGIN_DESIGN.read_text(encoding="utf-8")
    assert committed == expected, (
        "klc-plugin/agents/design.md is out of sync with core/agents/design.md — "
        "run `python3 core/skills/plugin_gen.py`"
    )


def test_no_fabricated_tool_in_design():
    """AC-8 (C-004): CLOSED-WORLD honesty guard. Every `<name>.py` reference in
    design.md must resolve to a real `core/skills` module, every real
    `module.attr` reference must resolve via `hasattr`, and no fabricated
    spine / invariant skill may be named (the spine framing is pure
    prose/structure — there is NO `core/skills/spine*.py`). Mirrors E-03's AC-7 /
    `plan_quality.unresolved_api_refs` shape."""
    sys.path.insert(0, str(_SKILLS))
    text = _read(_DESIGN)
    _EXT = {"yml", "yaml", "json", "md", "txt", "toml", "cfg", "ini"}

    # (a) every `<name>.py` reference resolves to a real core/skills module file.
    py_refs = re.findall(r"([A-Za-z0-9_-]+)\.py\b", text)
    assert py_refs, "expected at least one core/skills .py reference in design.md"
    for name in py_refs:
        assert (_SKILLS / f"{name}.py").exists(), (
            f"design.md references {name}.py but core/skills/{name}.py does not exist "
            f"(prompt/doc-honesty drift — AC-8/C-004)"
        )

    # (b) no fabricated spine / invariant skill or CLI.
    for forbidden in ("spine.py", "spine_", "invariant.py", "invariants.py",
                      "core/skills/spine"):
        assert forbidden not in text, (
            f"design.md must not reference a fabricated tool '{forbidden}' — "
            f"the spine framing is prose/structure only"
        )

    # (c) every `module.attr` token naming a real core/skills module resolves.
    for mod_name, attr in re.findall(r"`([a-z][a-z0-9_]+)\.([a-z][a-z0-9_]+)`", text):
        if attr in _EXT:
            continue  # a filename (models.yml, depgraph.json, spec.md), not an API attr
        if not (_SKILLS / f"{mod_name}.py").exists():
            continue  # not a core/skills module ref (e.g. spec.layer)
        module = importlib.import_module(mod_name)
        assert hasattr(module, attr), (
            f"design.md references {mod_name}.{attr} but core/skills/{mod_name}.py "
            f"exposes no such attribute (prompt/doc-honesty drift — AC-8/C-004)"
        )

    # Belt-and-suspenders: the spine invariants cross-link to D-NNN via the REAL
    # items index — the prompt must actually name it (cannot pass by claiming nothing).
    assert "core/skills/items.py" in text, (
        "spine invariants must cross-link to D-NNN via the real core/skills/items.py index"
    )
