"""tests/integration/test_klc110_ground_truth_diff.py — KLC-110 step-2: the
committed diff is resolved AT MOST ONCE per ack, through the same
`phase_completion._committed()` helper the drift producer already calls, and
the resolver stays single-sourced with drift-check (AC-7)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase_completion as _pc  # noqa: E402


def test_ground_truth_reuses_committed_diff_helper_merge_base_klc_excluded(monkeypatch):
    """AC-7: `_committed_cached` drives `phase_completion._committed()` — the
    merge-base-vs-origin/main (falling back to main) diff, `.klc/` excluded —
    and resolves it AT MOST ONCE per cache, so calling it twice with the same
    cache issues exactly one merge-base resolution and one diff invocation in
    total. A `.klc/` (lifecycle) path in the fake diff output never reaches
    the returned path set."""
    calls: list[list[str]] = []

    def fake_git(args, repo=None):
        calls.append(list(args))
        if args[0] == "merge-base":
            return "deadbeef"
        if args[0] == "diff":
            return "a.py\n.klc/tickets/KLC-999/meta.json\nb.py\n"
        return ""

    monkeypatch.setattr(_pc, "_git", fake_git)
    monkeypatch.setattr(_pc, "_load_modules", lambda: {"modules": []})

    cache: dict = {}
    mods1, paths1 = _pc._committed_cached(cache)
    mods2, paths2 = _pc._committed_cached(cache)

    assert paths1 == paths2 == {"a.py", "b.py"}
    assert ".klc/tickets/KLC-999/meta.json" not in paths1

    merge_base_calls = [c for c in calls if c[0] == "merge-base"]
    diff_calls = [c for c in calls if c[0] == "diff"]
    assert len(merge_base_calls) == 1, calls
    assert len(diff_calls) == 1, calls


def test_module_resolution_shared_with_committed_helper(monkeypatch):
    """Regression: the evaluator's module scoring and `_committed()`'s own
    module resolution both route through `module_membership.file_to_module`
    — a resolver change is observed identically by drift-check and by this
    ticket's scorer. Pinned here by asserting `_committed()`'s module
    resolution is exactly `module_membership.file_to_module`'s output for the
    committed paths, with no private matcher substituted in between."""
    import module_membership as _mm

    def fake_git(args, repo=None):
        if args[0] == "merge-base":
            return "deadbeef"
        if args[0] == "diff":
            return "core/skills/retrieval_eval.py\n"
        return ""

    modules_data = {"modules": [{"name": "core-skills", "path": "core/skills/"}]}
    monkeypatch.setattr(_pc, "_git", fake_git)
    monkeypatch.setattr(_pc, "_load_modules", lambda: modules_data)

    mods, paths = _pc._committed_cached(None)
    expected = _mm.file_to_module("core/skills/retrieval_eval.py", modules_data)
    assert paths == {"core/skills/retrieval_eval.py"}
    assert mods == {expected["primary_module"]} or mods == set(expected["member_of"])
