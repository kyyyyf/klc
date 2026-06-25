---
ticket: KLC-034
authority: generated
---

# Build log — KLC-034

## Step 1 — 2026-06-25
**Attempt**: has_upgrade_m_signal helper + advisory wiring
**Outcome**: green
**Notes**: Added `_UPGRADE_M_RE` and `has_upgrade_m_signal` to spec_structure.py mirroring `has_decompose_signal`. Wired advisory branch in `can_complete_discovery_lite` after the decompose branch. RED commit first, GREEN commit second.

## Step 2 — 2026-06-25
**Attempt**: AskUserQuestion directive in both discovery prompts
**Outcome**: green
**Notes**: Added `AskUserQuestion` tool directive to the Socratic sub-protocol step 2 in both `core/agents/discovery.md` and `core/agents/discovery-lite.md`. Preserved "one question at a time" and "2-3 approaches" markers (KLC-032 asserts depend on them). Verified existing socratic asserts still green.

## Step 3 — 2026-06-25
**Attempt**: AskUserQuestion permanent regression guard
**Outcome**: green
**Notes**: Added `test_discovery_prompts_use_askuserquestion` to `tests/test_prompt_regression.py`. Verified conceptual RED by checking `git show HEAD~2:core/agents/discovery.md | grep -c AskUserQuestion` returns 0.

## Step 4 — 2026-06-25
**Attempt**: Behavioural one-question-at-a-time judge fixture
**Outcome**: skipped (no ANTHROPIC_API_KEY in CI)
**Notes**: Added `tests/fixtures/klc-034-socratic-input.md` (multi-unknown scenario) and `test_one_question_at_a_time_judge_fixture` to `tests/test_prompt_regression.py`. Test skips gracefully without API key (CI-safe). Verified skip path runs correctly.

## Step 5 — 2026-06-25
**Attempt**: Documentation parity
**Outcome**: green
**Notes**: Updated docs/process.md (added "Discovery Socratic protocol (KLC-034)" section with AskUserQuestion + UPGRADE_M live signal table), docs/roles.md (agent discovery activity now cites AskUserQuestion), docs/process-artifacts.md (added options-lite.md entry in file layout + per-artifact schema with re-route signals). Verified `grep -rn "AskUserQuestion\|DISCOVERY_LITE_UPGRADE_M" docs/` returns content in all three files.

## Evidence

```
$ python3 -m pytest tests/integration/test_socratic_gate.py -q
.............
13 passed in 0.30s

$ python3 -m pytest tests/test_prompt_regression.py -q
.................s.....s.
23 passed, 2 skipped in 0.05s

$ python3 -m pytest tests/ -q --ignore=tests/fixtures
457 passed, 12 skipped in 165.99s (0:02:45)

$ grep -n "AskUserQuestion" core/agents/discovery.md core/agents/discovery-lite.md
core/agents/discovery.md:208:2. **Ask one question at a time.** Use the `AskUserQuestion` tool — exactly one
core/agents/discovery-lite.md:162:2. **Ask one question at a time.** Use the `AskUserQuestion` tool — exactly one

$ grep -n "has_upgrade_m_signal" core/skills/spec_structure.py core/skills/phase_completion.py
core/skills/spec_structure.py:13:_UPGRADE_M_RE = re.compile(r"\bDISCOVERY_LITE_UPGRADE_M\b")
core/skills/spec_structure.py:51:def has_upgrade_m_signal(text: str) -> bool:
core/skills/phase_completion.py:364:    if _spec_structure.has_upgrade_m_signal(text):

$ grep -rn "AskUserQuestion\|DISCOVERY_LITE_UPGRADE_M" docs/
docs/process-artifacts.md:117:| DISCOVERY_LITE_UPGRADE_M | ...
docs/roles.md:33:- Discovery: ... uses the AskUserQuestion tool ...
docs/process.md:735:Both discovery prompts ... use the AskUserQuestion tool
docs/process.md:745:| DISCOVERY_LITE_UPGRADE_M | S scope exceeds S ceiling | ...
```
