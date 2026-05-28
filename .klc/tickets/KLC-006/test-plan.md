---
ticket: KLC-006
authority: hybrid
last_generated: 2026-05-28T13:00:00Z
---

# Test plan — KLC-006

## Acceptance coverage

| AC | Test type | Test name / location | Notes |
|----|-----------|----------------------|-------|
| AC-1 | manual | New contributor walkthrough | Human validates: can execute ticket end-to-end using only `docs/` without reading source code |
| AC-2 | acceptance | tests/docs/test_phase_coverage.py::test_all_phases_documented | Verify `docs/phases/<phase>.md` exists for every phase in `config/phases.yml` |
| AC-3 | acceptance | tests/docs/test_tracks_decision_tree.py::test_tracks_doc_exists | Verify `docs/tracks.md` contains decision flowchart with examples |
| AC-4 | acceptance | tests/docs/test_glossary_completeness.py::test_all_terms_defined | Verify `docs/glossary.md` defines all terms referenced in docs |
| AC-5 | acceptance | tests/docs/test_agent_prompts_no_duplication.py::test_phase_purpose_moved | Verify `core/agents/*.md` no longer duplicate phase purpose (must reference `docs/phases/`) |
| AC-6 | acceptance | tests/docs/test_markdown_links.py::test_all_links_resolve | Verify all markdown links resolve, no orphan files in `docs/` |

## Edge cases

- **Empty glossary**: If no terms are defined in `docs/glossary.md`, AC-4 should warn but not fail (degrades to warning if `docs/` has no term references).
- **Phase yml changes**: If `config/phases.yml` is updated after doc creation, AC-2 test should fail to signal docs are stale.
- **Broken symlinks**: AC-6 must detect symlinks pointing to nonexistent targets.
- **Case sensitivity**: Links like `[Discovery](discovery.md)` vs `[Discovery](Discovery.md)` may break on case-sensitive filesystems — test should validate actual filesystem paths.

## Regression scenarios

- **Affected module `docs/`**: Ensure `docs/process.md` trimmed but still comprehensible (no critical sections removed).
- **Affected module `core/agents/`**: After adding headers to `core/agents/*.md`, agent system still loads prompts correctly (no parsing breakage from header syntax).
- **CLI still functional**: Running `klc status`, `klc ack`, etc. after doc changes does not regress (agents can still read their prompts).

## Manual checklist

- [ ] New contributor (or simulated fresh user) can follow `docs/roles.md` to understand their role
- [ ] `docs/tracks.md` decision tree walks through XS/S/M/L selection with real examples
- [ ] All 11 `docs/phases/*.md` files follow the template (Purpose, Inputs, Outputs, Completion criteria, Ack rules, Common pitfalls, Example)
- [ ] `docs/glossary.md` includes at minimum: phase, track, AC, artefact, ack, rework, manual, layer, affected_modules
- [ ] `core/agents/*.md` headers point to correct `docs/phases/<phase>.md` files
- [ ] Spot-check 3 markdown links in `docs/` to verify they resolve

<!-- BEGIN: manual -->
<!-- Human additions to the plan -->
<!-- END: manual -->
