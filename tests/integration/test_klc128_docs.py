"""KLC-128 step-6 — AC-13: `docs/process.md` §Integrate and
`docs/architecture.md` describe the ground-truth sources, their order and the
pre-merge recording, and the false 'same ground truth ... can never
disagree' claim is corrected."""
from __future__ import annotations

import re
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_PROCESS_MD = _FW_ROOT / "docs" / "process.md"
_ARCHITECTURE_MD = _FW_ROOT / "docs" / "architecture.md"


def _flatten(text: str) -> str:
    """Collapse markdown line-wrap whitespace (a phrase split across two
    wrapped lines) into single spaces, so a substring check is not brittle
    against where the prose happens to wrap."""
    return re.sub(r"\s+", " ", text)


def _integrate_section() -> str:
    text = _PROCESS_MD.read_text(encoding="utf-8")
    m = re.search(r"^## Integrate\n(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert m, "docs/process.md must have a §Integrate section"
    return _flatten(m.group(1))


def test_process_md_integrate_section_documents_ground_truth_sources_order_and_recording():
    """AC-13, part 1/2: §Integrate names all three ground-truth sources in
    resolution order (live-merge-base, recorded-range, none), states which
    acks record the range (build, review, manual), and states the D-001
    staleness caveat in substance (a commit landing after the last recording
    ack is missed; an amend/rebase afterward can make the range over-count
    and trigger a false integrate expansion block)."""
    section = _integrate_section()

    i_live = section.index("live-merge-base")
    i_recorded = section.index("recorded-range")
    i_none = section.index("none")
    assert i_live < i_recorded < i_none, \
        "the three sources must appear in resolution order"

    assert "build" in section and "review" in section and "manual" in section

    lowered = section.lower()
    assert "after the last recording ack" in lowered
    assert "amend" in lowered and "rebase" in lowered
    assert "over-count" in lowered
    assert "expansion" in lowered


def test_architecture_md_same_ground_truth_claim_is_corrected_and_no_longer_false():
    """AC-13, part 2/2: the old unqualified 'the two can never disagree'
    wording (F-004's false claim) is gone, replaced with wording naming
    `integrate_ground_truth` and the D-001 staleness caveat — not a second,
    independent claim."""
    text = _flatten(_ARCHITECTURE_MD.read_text(encoding="utf-8"))

    # The specific false claim (F-004) — not every unrelated use of the phrase
    # "can never disagree" elsewhere in this doc (e.g. the IDF-vocabulary one).
    assert "the same ground truth drift-check reports on, so the two can never disagree" not in text
    assert "integrate_ground_truth" in text
    assert "same file set" in text or "same ground truth" in text
