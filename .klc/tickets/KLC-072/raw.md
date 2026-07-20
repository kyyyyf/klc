---
ticket: KLC-072
kind_hint: bug
created: 2026-07-18T08:56:28Z
---
Fix CLI/vscode dispatch bugs found by review: (1) scripts/klc routes 'metrics' and 'reindex' via OPERATIONAL_CMDS before their explicit handlers -> 'command not implemented'; (2) 'jira-sync' routed via _run_phase looks for core/phases/jira_sync.py but the wrapper is jira_sync_cmd.py -> fails; (3) vscode-extension klcReader.ts parses KLC_FRAMEWORK_ROOT/$FW but klc install writes KLC_FW -> resolveFrameworkRoot() returns null, tree reports framework missing; (4) build:work prompt cards are build/_prompt_step_<impl_step>.md but klcReader.ts + status.py + treeProvider only check build/_prompt.md / omit the required single pick -> wrong next-action shown at build:work / build:ack-needed. Pre-existing on main, surfaced during KLC-070 drift review; not part of the planning-index epic.
