---
ticket: KLC-013
kind_hint: feature
created: 2026-05-29T13:08:15Z
---
Phase 2 — discovery-lite + intake routing. Add core/skills/route_heuristic.py (deterministic, no LLM): kind+raw length+keywords+modules.json match -> route_hint in meta.json. Update intake.ack picks (confirm-route/force-full-discovery/force-xs-skip). Add core/agents/discovery-lite.md (~50 lines, lite spec schema, [!ASSUMPTION] over blocking [!QUESTION]). New phase id discovery-lite for [XS,S], keep discovery for [M,L]. Update phase_completion, models.yml (per_track.XS.discovery-lite=local-simple). Ollama fallback in runner.py. See plan.md Phase 2.
