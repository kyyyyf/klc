"""Prompt-structural tests for KLC-090 (E-03 · discovery enrichment).

E-03 is a PROMPT-layer ticket: it wires the merged elicitation engine
(`core/skills/elicitation.py`, KLC-088) and the technique picker
(`core/skills/elicitation_techniques.py`, KLC-087) into the two discovery
agent prompts. There is no new runtime code, so the acceptance signal is a
set of prompt-structural assertions that pin every prose claim added to
`discovery.md` / `discovery-lite.md` to a REAL wired entry point.

This is the epic's anti-drift mechanism (AC-7, C-003): the recurring failure
class on 083/084/085/088 was prompt prose promising a capability the code did
not back. Each test below asserts that the prompt both instructs the required
behaviour AND names the real API/CLI that provides it — a prompt promising
something the merged modules do not expose FAILS here.
"""
from __future__ import annotations

import re
import sys

from tests.prompt_harness import _FW_ROOT

_AGENTS = _FW_ROOT / "core" / "agents"
_DISCOVERY = _AGENTS / "discovery.md"
_DISCOVERY_LITE = _AGENTS / "discovery-lite.md"
_BOTH = (_DISCOVERY, _DISCOVERY_LITE)


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# step-1 — elicitation wiring + `## Assumptions` section + guess-by-default
# ---------------------------------------------------------------------------

def test_both_prompts_call_elicitation():
    """AC-1: both prompts instruct the agent to run the elicitation coverage
    scan on its draft mid-phase, naming the real engine entry point (the CLI
    `elicitation.py --file <draft> --track <track>` and/or `elicitation.elicit`)
    and surfacing the reported coverage gaps as what it asks / records."""
    for path in _BOTH:
        text = _read(path)
        low = text.lower()
        # names the real engine
        assert "elicitation.elicit" in text, (
            f"{path.name}: must name the real engine entry point elicitation.elicit"
        )
        # names the real CLI invocation with both required flags
        assert "elicitation.py" in text and "--file" in text and "--track" in text, (
            f"{path.name}: must show the real CLI `elicitation.py --file <draft> --track <track>`"
        )
        # instructs a mid-draft run + surfacing of coverage gaps
        assert "coverage" in low, f"{path.name}: must speak of coverage gaps to surface"
        assert "draft" in low, f"{path.name}: must instruct running on the draft spec mid-phase"


def test_both_prompts_have_assumptions_section():
    """AC-2: both prompts add an `## Assumptions` section to the spec.md template."""
    for path in _BOTH:
        text = _read(path)
        assert "## Assumptions" in text, (
            f"{path.name}: spec template must carry an `## Assumptions` section"
        )


def test_both_prompts_have_guess_by_default_rule():
    """AC-2: both prompts carry the guess-by-default rule — infer a reasonable
    default and record it, escalating to a marker / decision ONLY on high
    impact × ambiguity."""
    for path in _BOTH:
        low = _read(path).lower()
        assert "guess-by-default" in low or "infer a reasonable default" in low, (
            f"{path.name}: must state the guess-by-default rule (infer a reasonable default)"
        )
        # escalate only on high impact x ambiguity
        assert "high" in low and "impact" in low and "ambiguit" in low, (
            f"{path.name}: must escalate to a marker/decision only on high impact × ambiguity"
        )


# ---------------------------------------------------------------------------
# step-2 — anti-authoring discipline + 5-Whys/Impact-Mapping Goals + batch 2–4
# ---------------------------------------------------------------------------

def test_both_prompts_state_anti_authoring():
    """AC-3: both prompts state the anti-authoring discipline — coach not quiz,
    elicitation not direction (hand the pen back), do not invent the requester's
    intent."""
    for path in _BOTH:
        low = _read(path).lower()
        assert "coach" in low, f"{path.name}: must say 'coach' (coach, don't quiz)"
        assert "hand the pen back" in low, (
            f"{path.name}: must say 'hand the pen back' (elicitation, not direction)"
        )
        assert "not direction" in low or "not quiz" in low, (
            f"{path.name}: must frame it as elicitation, not direction / not a quiz"
        )
        assert "invent" in low, (
            f"{path.name}: must say do not invent the requester's intent"
        )


def test_both_prompts_frame_goals_5whys_impact_mapping():
    """AC-4: both prompts frame the Goals section via 5 Whys and Impact Mapping
    (Goal → Actors → Impacts)."""
    for path in _BOTH:
        text = _read(path)
        low = text.lower()
        assert "5 whys" in low, f"{path.name}: must frame Goals via 5 Whys"
        assert "impact mapping" in low, f"{path.name}: must frame Goals via Impact Mapping"
        # the Goal -> Actors -> Impacts trace
        assert "actors" in low and "impacts" in low, (
            f"{path.name}: Impact Mapping must trace Goal → Actors → Impacts"
        )


def test_never_batch_removed_and_batch_2_4_present():
    """AC-5 / C-002: the never-batch rule is GONE from both prompts and replaced
    with the batch-2–4-via-AskUserQuestion rule (consistent with
    config/clarify.yml: style: batch)."""
    for path in _BOTH:
        text = _read(path)
        low = text.lower()
        # the contradiction must be fully removed
        assert "never batch" not in low, f"{path.name}: 'never batch' text must be removed"
        assert "one question at a time" not in low, (
            f"{path.name}: 'one question at a time' rule must be removed (reconciled to batch)"
        )
        assert "exactly one question" not in low, (
            f"{path.name}: 'exactly one question per call' must be removed"
        )
        # the new batch rule, pinned to AskUserQuestion
        assert "2-4" in text or "2–4" in text, (
            f"{path.name}: must state the batch-2–4 rule"
        )
        assert "AskUserQuestion" in text, (
            f"{path.name}: batch rule must be delivered via AskUserQuestion"
        )
        # ordered by Impact × Uncertainty, recommended option first
        assert "impact" in low and "uncertainty" in low, (
            f"{path.name}: batch must be ordered by Impact × Uncertainty"
        )
        assert "recommend" in low, (
            f"{path.name}: batch must lead with a recommended option"
        )


# ---------------------------------------------------------------------------
# step-3 — M/L technique-picker offer via should_offer + prompt-honesty roll-up
# ---------------------------------------------------------------------------

def test_discovery_offers_picker_on_ml():
    """AC-6: discovery.md offers the technique picker via should_offer / pick,
    gated to tracks M and L (or a flagged ambiguity)."""
    text = _read(_DISCOVERY)
    assert "elicitation_techniques.should_offer" in text, (
        "discovery.md must offer the picker via elicitation_techniques.should_offer"
    )
    assert "elicitation_techniques.pick" in text or "pick(" in text, (
        "discovery.md must surface candidates via elicitation_techniques.pick"
    )
    low = text.lower()
    # gated to M/L or a flagged ambiguity
    assert ("m/l" in low) or ("m and l" in low) or ("flagged" in low and "ambiguit" in low), (
        "discovery.md picker offer must be gated to M/L or a flagged ambiguity"
    )


def test_picker_offer_names_should_offer_and_never_apply():
    """AC-6 / C-004: the offer names should_offer and states the picker is never
    applied without a human yes — the module has no apply/run entry point."""
    text = _read(_DISCOVERY)
    low = text.lower()
    assert "should_offer" in text
    assert "never" in low and "without" in low and "yes" in low, (
        "discovery.md must state the technique is never applied without a human yes"
    )
    assert "no apply" in low or "no apply/run" in low or "only selects" in low or "selection only" in low, (
        "discovery.md must state the picker only selects (no apply/run)"
    )


def test_discovery_lite_states_picker_gated_off():
    """AC-6 / Q-002: discovery-lite.md states the picker is gated OFF on XS/S by
    default (should_offer=False), reachable only via a flagged ambiguity."""
    text = _read(_DISCOVERY_LITE)
    low = text.lower()
    assert "should_offer" in text, (
        "discovery-lite.md must name should_offer to explain the gate"
    )
    assert "xs" in low and ("gated off" in low or "off by default" in low or "not offered" in low), (
        "discovery-lite.md must state the picker is gated off on XS/S by default"
    )
    assert "flagged" in low and "ambiguit" in low, (
        "discovery-lite.md must state a flagged ambiguity is the only path onto XS/S"
    )


def test_decisions_recorded_into_spec_not_auto_routed():
    """FIX 2 (codex-P2): elicitation's `decisions[]` are TRANSIENT CLI output. The
    ack decision gate (`spec_review.consume`) only consumes decisions from a
    PERSISTED reviewer artifact (`spec-review.md`) — it never parses the elicitation
    output — so a high-impact decision DISAPPEARS unless the agent records it into
    the `spec.md` artifact the discovery gate actually reads. Both prompts must
    instruct RECORDING those outputs (as `[!QUESTION]`/`[NEEDS CLARIFICATION]` and
    `## Assumptions` lines), and must NOT claim an auto-flow into the decision gate."""
    for path in _BOTH:
        text = _read(path)
        low = text.lower()
        # honest about the transient CLI output + the recording obligation
        assert "transient" in low, (
            f"{path.name}: must state the elicitation CLI output is transient"
        )
        assert "record" in low, (
            f"{path.name}: must instruct recording elicitation's outputs into spec.md"
        )
        # the dishonest auto-flow claim must be gone (ignore backticks/markup)
        flat = text.replace("`", "").lower()
        assert "decisions[] into the ack decision gate" not in flat, (
            f"{path.name}: must not claim elicitation decisions auto-flow into the ack gate"
        )
        assert "flow into the existing discovery ack decision gate" not in flat, (
            f"{path.name}: must not claim elicitation decisions auto-flow into the ack gate"
        )
    # discovery.md (M/L) records high-impact decisions as [!QUESTION Q-NNN] or a marker.
    disc = _read(_DISCOVERY)
    assert "[!QUESTION" in disc, (
        "discovery.md: high-impact decisions must be recorded as [!QUESTION Q-NNN] items"
    )
    assert "[NEEDS CLARIFICATION]" in disc
    # discovery-lite (XS/S) reserves [NEEDS CLARIFICATION] for genuine no-default
    # unknowns (markers[]); defaultable decisions become non-blocking assumptions.
    lite = _read(_DISCOVERY_LITE)
    assert "[NEEDS CLARIFICATION]" in lite


def test_discovery_lite_decisions_are_nonblocking_assumptions():
    """P2 (scoped re-review): elicitation `decisions[]` are DEFAULTABLE (a defensible
    `recommended` default exists → non-blocking is the point). The discovery-lite ack
    (`can_complete_discovery_lite`) BLOCKS on any open `[NEEDS CLARIFICATION]` marker,
    so recording a routine defaultable decision as a marker would STOP a normal XS/S
    ticket — breaking the guess-by-default / non-blocking contract. discovery-lite
    must map `decisions[]` → `## Assumptions` and reserve `[NEEDS CLARIFICATION]` for
    `markers[]` only."""
    text = _read(_DISCOVERY_LITE)
    low = text.lower()
    # markers[] still map to the blocking marker (that is correct — no safe default).
    assert "[NEEDS CLARIFICATION]" in text
    # decisions[] map to the non-blocking assumptions form.
    assert "## Assumptions" in text
    # the mapping must be stated explicitly and reserve the marker for markers[].
    assert "reserved for" in low and "markers[]" in low, (
        "discovery-lite must reserve [NEEDS CLARIFICATION] for markers[] only"
    )
    # must forbid converting a defaultable decision into a blocking marker.
    assert "do not convert a decision" in low or "not convert a decision" in low, (
        "discovery-lite must forbid converting a decision into a blocking marker"
    )
    # negative: the previous over-correction (record a decision as a marker) is gone.
    norm = " ".join(low.split())
    assert "decision into `spec.md` yourself as an inline `[needs clarification]`" not in norm, (
        "discovery-lite must not instruct recording a decision as a [NEEDS CLARIFICATION] marker"
    )


def test_discovery_ml_decisions_are_nonblocking():
    """M/L check: a plain `[!QUESTION Q-NNN]` WITHOUT `blocks=discovery` only SURFACES
    at the decision gate — `can_complete_discovery` blocks only on
    `[NEEDS CLARIFICATION]` markers and duplicate AC ids, not on a plain `[!QUESTION]`.
    So discovery.md must record defaultable `decisions[]` as a non-blocking
    `[!QUESTION Q-NNN]` (no `blocks=discovery`) and reserve the blocking
    `[NEEDS CLARIFICATION]` for `markers[]`."""
    text = _read(_DISCOVERY)
    low = text.lower()
    assert "[!QUESTION" in text and "[NEEDS CLARIFICATION]" in text
    assert "non-blocking" in low, "discovery.md must call the decision QUESTION non-blocking"
    assert "blocks=discovery" in text, (
        "discovery.md must warn that adding blocks=discovery would force a STOP"
    )
    assert "reserved for" in low and "markers[]" in low, (
        "discovery.md must reserve [NEEDS CLARIFICATION] for markers[]"
    )


def test_every_claim_pinned_to_api():
    """AC-7 (C-003): CLOSED-WORLD anti-drift guard. Extract EVERY
    `elicitation(_techniques).<attr>` reference from both prompt bodies and assert
    each attribute resolves via `hasattr` on the imported module. A future prompt
    edit adding a fabricated `elicitation_techniques.apply(...)` therefore FAILS
    here — the hard-coded allowlist that let it slide is gone (fresh-LOW). Mirrors
    the shape of `plan_quality.unresolved_api_refs`."""
    sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
    import elicitation
    import elicitation_techniques

    modules = {
        "elicitation": elicitation,
        "elicitation_techniques": elicitation_techniques,
    }
    # `module.attr` where module is one of the two engines. `\w+` after the dot; the
    # `(?!\w*\.py\b)` negative lookahead skips the FILE reference `elicitation.py` /
    # `elicitation_techniques.py` (a path, not an API attribute).
    ref_re = re.compile(r"\b(elicitation(?:_techniques)?)\.(?!py\b)(\w+)")

    for path in _BOTH:
        text = _read(path)
        refs = ref_re.findall(text)
        assert refs, f"{path.name}: expected at least one elicitation API reference"
        for module_name, attr in refs:
            mod = modules[module_name]
            assert hasattr(mod, attr), (
                f"{path.name}: prompt references {module_name}.{attr} but "
                f"core/skills/{module_name}.py exposes no such attribute "
                f"(prompt/doc-honesty drift — AC-7/C-003)"
            )

    # Belt-and-suspenders: the specific wired names each prompt claims must be present
    # (a prompt could otherwise satisfy the closed-world check by claiming nothing).
    disc = _read(_DISCOVERY)
    lite = _read(_DISCOVERY_LITE)
    for name in ("elicitation.elicit", "elicitation_techniques.should_offer",
                 "elicitation_techniques.pick"):
        assert name in disc, f"discovery.md claims behaviour but omits API name {name}"
    for name in ("elicitation.elicit", "elicitation_techniques.should_offer"):
        assert name in lite, f"discovery-lite.md claims behaviour but omits API name {name}"

    # The CLI `--risk-tags` flag is a CLI ARG, not an `elicitation.<attr>` — so it
    # must NOT be flagged by the closed-world api-ref scan above.
    for path in _BOTH:
        assert not ref_re.findall("--risk-tags"), "the --risk-tags CLI flag must not trip the api-ref scan"


# ---------------------------------------------------------------------------
# review fix P2 — risk_tags reach the CLI so risk-aligned gaps get the boost
# ---------------------------------------------------------------------------

def test_prompts_pass_risk_tags_to_cli():
    """Both prompts must instruct passing `risk_tags` to the engine CLI via
    `--risk-tags <tags>`, sourcing them PRIMARILY from the DRAFT `spec.md`
    frontmatter the agent is writing.

    Sequencing bug guarded here: `meta.json.risk_tags` is empty during discovery —
    `phase_completion._sync_risk_tags` copies them from the `spec.md` frontmatter into
    `meta.json` ONLY at/after ack. So a prompt that told the agent to read the tags
    from `meta.json` would read an empty field mid-discovery and silently lose the
    risk boost. The draft frontmatter is where the tags actually live at discovery
    time, so it must be the primary source."""
    for path in _BOTH:
        text = _read(path)
        low = text.lower()
        assert "--risk-tags" in text, (
            f"{path.name}: must instruct the CLI `--risk-tags` flag for risk-aligned boosting"
        )
        assert "risk_tags" in text, f"{path.name}: must name risk_tags"
        # Isolate the risk-tags instruction region (between the flag syntax in the
        # code fence and the JSON-output description) so an unrelated 'frontmatter'
        # mention elsewhere (e.g. discovery-lite rule 6) cannot false-green this.
        assert "[--risk-tags <tags>]" in text, f"{path.name}: CLI fence must show the flag"
        region = text.split("[--risk-tags <tags>]", 1)[1].split("It prints one JSON", 1)[0]
        rlow = region.lower()
        assert "frontmatter" in rlow, (
            f"{path.name}: risk-tags instruction must source from the draft spec.md frontmatter"
        )
        assert "draft" in rlow or "spec.md" in rlow, (
            f"{path.name}: risk-tags source must be the DRAFT spec.md the agent is writing"
        )
        # the buggy pre-ack instruction ("`risk_tags` (read them from `meta.json`)")
        # must be gone. An honest "do NOT read them from meta.json" warning is fine —
        # so match the specific buggy parenthetical, not any mention of meta.json.
        flat = " ".join(low.split())
        assert "`risk_tags` (read them from `meta.json`)" not in flat, (
            f"{path.name}: must not instruct reading risk_tags from meta.json as the "
            f"source (empty pre-ack — the sequencing bug)"
        )


def _run_elicitation_cli(spec_text: str, track: str, risk_tags: str | None = None) -> dict:
    """Invoke the real elicitation.py CLI on a temp draft and return its parsed JSON."""
    import json as _json
    import os as _os
    import subprocess as _sp
    import tempfile as _tf

    cli = _FW_ROOT / "core" / "skills" / "elicitation.py"
    with _tf.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(spec_text)
        draft = fh.name
    try:
        cmd = [sys.executable, str(cli), "--file", draft, "--track", track]
        if risk_tags is not None:
            cmd += ["--risk-tags", risk_tags]
        env = dict(_os.environ, PROJECT_ROOT=str(_FW_ROOT))
        proc = _sp.run(cmd, capture_output=True, text=True, env=env, cwd=str(_FW_ROOT))
        assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
        return _json.loads(proc.stdout)
    finally:
        _os.unlink(draft)


def test_cli_risk_tags_boosts_routing():
    """The CLI `--risk-tags` flag reaches `elicit(..., signals=...)`: a Partial
    `domain-data-model` on a `data`-risk ticket is boosted from a silent assumption
    (base impact 3 × Partial 1 = 3, below threshold) to a routed decision (boosted
    impact 4 × 1 = 4, at threshold) — mirroring the module-level round-6 risk-boost
    test through the CLI path. Confirms the JSON shape is unchanged."""
    spec = "# Widget\n\nThis widget processes some data for the operator.\n"

    base = _run_elicitation_cli(spec, "S")
    assert set(base) == {"coverage", "questions", "markers", "decisions", "assumptions"}, (
        "CLI JSON shape must be unchanged"
    )
    base_decisions = {d["ref"] for d in base["decisions"]}
    assert "domain-data-model" not in base_decisions, "without --risk-tags: an assumption, not a decision"
    assert any(a.startswith("- domain-data-model:") for a in base["assumptions"])

    boosted = _run_elicitation_cli(spec, "S", risk_tags="data")
    boosted_decisions = {d["ref"] for d in boosted["decisions"]}
    assert "domain-data-model" in boosted_decisions, "--risk-tags data must boost domain-data-model to a decision"
    assert not any(a.startswith("- domain-data-model:") for a in boosted["assumptions"])


# ---------------------------------------------------------------------------
# review fix P2d — draft-first ordering coherence in the Socratic sub-protocol
# ---------------------------------------------------------------------------

def _socratic_section(text: str) -> str:
    """The `## Socratic sub-protocol …` section of a prompt (up to the next `## `)."""
    start = text.index("## Socratic sub-protocol")
    nxt = text.find("\n## ", start + 1)
    return text[start:] if nxt == -1 else text[start:nxt]


def test_socratic_ordering_is_draft_first():
    """The coverage `questions[]` queue only EXISTS after the agent has drafted a
    rough spec.md and run `elicitation.py` on it. So the ordered Socratic protocol
    must NOT tell the agent to ask from `questions[]` before any draft exists — it
    must (a) be framed as 'before FINALIZING' (draft-then-refine), not 'before
    writing', and (b) place the rough-draft + elicitation-run step BEFORE the
    coverage-driven 'ask from questions[]' step."""
    for path in _BOTH:
        sec = _socratic_section(_read(path))
        low = sec.lower()
        # (a) draft-then-refine framing, not "ask everything before any draft exists"
        assert "before writing `spec.md`, work through" not in low, (
            f"{path.name}: Socratic protocol must not be framed 'before writing' — the "
            f"elicitation queue needs a draft first"
        )
        assert "before finalizing" in low, (
            f"{path.name}: Socratic protocol must be framed as 'before finalizing' (draft-then-refine)"
        )
        # (b) the rough-draft + elicitation-run instruction precedes the questions[] ask.
        draft_idx = low.find("rough")
        run_idx = low.find("run coverage elicitation")
        ask_idx = low.find("`questions[]` queue")
        assert draft_idx != -1, f"{path.name}: Socratic protocol must instruct a rough draft first"
        assert run_idx != -1, f"{path.name}: Socratic protocol must run coverage elicitation on the draft"
        assert ask_idx != -1, f"{path.name}: Socratic protocol must ask from the questions[] queue"
        assert draft_idx < ask_idx, (
            f"{path.name}: the rough-draft step must precede asking from questions[]"
        )
        assert run_idx < ask_idx, (
            f"{path.name}: the elicitation run must precede asking from questions[]"
        )


def test_elicitation_invocation_is_runnable():
    """P2d follow-up: the CLI must be invoked in the runnable form
    `python3 core/skills/elicitation.py …` — a bare `elicitation.py --file …` is not
    on PATH / executable in this repo, so an agent following it literally would fail
    the draft-first elicitation step."""
    import re as _re
    for path in _BOTH:
        text = _read(path)
        # every `elicitation.py --file` occurrence must be prefixed by the python3 + path form
        for m in _re.finditer(r"elicitation\.py\s+--file", text):
            start = max(0, m.start() - 40)
            preceding = text[start:m.start()]
            assert "python3 core/skills/" in preceding, (
                f"{path.name}: `elicitation.py --file` must be invoked as "
                f"`python3 core/skills/elicitation.py --file` (runnable form)"
            )
