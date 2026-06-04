---
ticket: KLC-018
kind_hint: bug
created: 2026-06-04T13:55:03Z
---
Kodex-review remediation (bundles KLC-011..016 review findings).

PRIMARY: KLC-013 (discovery-lite + intake routing) is NOT in main. Branch
feature/KLC-013-discovery-lite (commit 277f2b7) was never merged. main has
only `discovery` for all tracks; route_heuristic.py is absent; discovery-lite.md
exists only as an orphan file accidentally added by KLC-014. Restore the full
KLC-013 functionality (rebased onto current main) and close its under-spec
gaps at the same time.

Findings to fix (all from .klc/tickets/KLC-0{11..16}/kodex-review.md):

[A] KLC-013 restore + harden (PRIMARY):
  - merge/port discovery-lite phase for [XS,S], discovery for [M,L]
  - route_heuristic.py + intake route picks (confirm-route/force-full-discovery/force-xs-skip)
  - force-xs-skip allowed only when route_hint=="XS" (guard)
  - can_complete_discovery_lite checks estimate.total vs track AND affected_modules>=1
  - Ollama fallback resolves explicit fallback role, not resolve("indexing")

[B] KLC-015 review cascade not wired (bug):
  - call review_cascade.decide() from scripts/review.py before sub-agents
  - fail-closed: empty file_tiers (classifier failed) or skipped scope -> full review

[C] KLC-016 telemetry envelope (bug):
  - split provider envelope: write only result text to artifact, parse usage separately
  - then enable --output-format json by default for anthropic
  - persist OpenAI usage too
  - NOTE: source=provider already fixed by KLC-017, do not redo

[D] KLC-012 scope_delta holes (bug):
  - files outside known module prefixes -> explicit bucket counted as expansion
  - skipped (no modules.json / no diff) for guarded phases -> hard-fail or explicit override

[E] KLC-014 condition validation (tech):
  - validate_config.py checks condition: syntax in phases.yml (catch typos)
  - validate risk_tags in discovery completion instead of silent swallow
  - runtime stays fail-open (do not change _eval_condition return True)

KLC-011: verified clean, no action.
