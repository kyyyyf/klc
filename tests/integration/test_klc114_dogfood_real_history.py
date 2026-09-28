"""KLC-114 step-2: the normalised scope rule replayed over the real git
history of four archived tickets (KLC-113/115/117/118) — the RED that
matters for AC-2. Under the revision-1 rule (before the annotation-stripping
fix) this reported 92 strays across 11 steps, every one a notation
artefact. `.klc/` is gitignored, so the four impl-plan texts are frozen
under `tests/fixtures/klc114-dogfood/` (D-206); the commits themselves are
read from THIS repo's real git history via `tdd_order.step_commits`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import impl_plan_check as ipc  # noqa: E402
import step_ledger as sl  # noqa: E402
import tdd_order as td  # noqa: E402

_FIXTURES = _FW_ROOT / "tests" / "fixtures" / "klc114-dogfood"
_TICKETS = ("KLC-113", "KLC-115", "KLC-117", "KLC-118")

# Steps whose revision-1 strays were ENTIRELY notation artefacts (a trailing
# `(new)`/`(modified)` written inside backticks, F-1) — 63 of the 92.
NOTATION_ONLY = [("KLC-113", n) for n in (2, 3, 4, 5)] + \
                [("KLC-115", n) for n in (1, 2, 4)]

# A frozen baseline, not a zero (D-207). Each entry was checked by hand
# against that ticket's impl-plan and is genuine, already-acked scope drift.
GENUINE_DRIFT = {
    ("KLC-115", "step-8"): ["config/settings.yml",
                            "core/agents/_includes/completion-signal.md"],
    ("KLC-117", "step-2"): ["core/skills/drift_review.py"],
    ("KLC-117", "step-3"): ["core/skills/implplan_review.py",
                            "core/skills/testplan_review.py"],
    ("KLC-118", "step-1"): ["vscode-extension/src/klcReader.ts"],
}


class _DogfoodCorpus:
    def __init__(self):
        self._plans = {}
        for ticket in _TICKETS:
            text = (_FIXTURES / ticket / "impl-plan.md").read_text(encoding="utf-8")
            self._plans[ticket] = ipc.parse_impl_plan_steps(text)

    def _step(self, ticket, n):
        target = f"step-{n}"
        for s in self._plans[ticket]:
            if s["id"] == target:
                return s
        raise KeyError((ticket, n))

    def stray(self, ticket, n):
        step = self._step(ticket, n)
        fields = ipc.extract_step_fields(step["body"])
        commits = td.step_commits(ticket, n, None)
        touched = sl._touched_paths(commits, None)
        return sl._out_of_scope(touched, fields["affected"])

    def all_stray(self):
        out = {}
        for ticket in _TICKETS:
            for s in self._plans[ticket]:
                n = int(re.search(r"\d+", s["id"]).group())
                stray = self.stray(ticket, n)
                if stray:
                    out[(ticket, s["id"])] = stray
        return out


@pytest.fixture(scope="module")
def dogfood_corpus():
    # A-203: absence of evidence is not evidence of failure — skip (not fail)
    # when the four archived tickets' step commits are not reachable from
    # this branch (e.g. a shallow clone), rather than reporting a vacuous
    # "zero strays" pass.
    if not td.step_commits("KLC-113", 1, None):
        pytest.skip("KLC-113/115/117/118 step commits not reachable from this "
                    "branch (shallow clone?) — A-203")
    return _DogfoodCorpus()


def test_notation_only_steps_report_zero_scope_violations(dogfood_corpus):
    """AC-2: a step whose revision-1 strays were entirely notation
    artefacts reports zero scope violations under the normalising matcher."""
    for ticket, n in NOTATION_ONLY:
        assert dogfood_corpus.stray(ticket, n) == [], f"{ticket} step-{n}"


def test_whole_corpus_matches_the_frozen_genuine_drift_baseline(dogfood_corpus):
    """AC-2: the normalised rule replayed over the real git history of
    KLC-113/115/117/118 reproduces exactly the frozen, hand-verified genuine
    scope drift for these four already-acked builds — no more, no fewer."""
    assert dogfood_corpus.all_stray() == GENUINE_DRIFT
