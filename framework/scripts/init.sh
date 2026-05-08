#!/usr/bin/env bash
# init.sh — first-time bootstrap.
#
# Runs the full pipeline:
#   1. install-deps check
#   2. file-scanner          (structural snapshot)
#   3. Serena start hint     (user-managed MCP; we only prepare inputs)
#   4. dep-graph             (per-language)
#   5. inventory agent       (LLM step, invoked from Claude Code)
#   6. decompose agent       (LLM)
#   7. docgen agent          (LLM)
#   8. store HEAD sha in framework/.last-run
#
# This script is a *driver*: steps 5-7 are LLM agents and are not executed
# directly from bash. The script prepares their inputs and prints the exact
# prompt to run inside Claude Code. All text is English.

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$FRAMEWORK_ROOT/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p "$FRAMEWORK_ROOT/logs" "$FRAMEWORK_ROOT/index"

log()  { echo "[init] $*"; }
die()  { echo "[init][err] $*" >&2; exit 1; }

log "Project root: $PROJECT_ROOT"

# 1. Dependencies ------------------------------------------------------------
#log "Step 1/8: checking dependencies"
#if ! bash "$FRAMEWORK_ROOT/scripts/install-deps.sh"; then
#  die "dependencies missing — resolve the suggestions above and rerun ./framework/scripts/init.sh"
#fi

# 2. Structural scan --------------------------------------------------------
log "Step 2/8: structural scan (file-scanner.sh)"
bash "$FRAMEWORK_ROOT/skills/file-scanner.sh" "$PROJECT_ROOT" \
  > "$FRAMEWORK_ROOT/index/structural.json" \
  || die "file-scanner.sh failed"
log "  -> framework/index/structural.json"

# 3. MCP bootstrap hint -----------------------------------------------------
log "Step 3/8: MCP configuration"
if [ -f "$PROJECT_ROOT/.mcp.json" ]; then
  log "  .mcp.json already present; assuming Serena / ast-grep are configured."
else
  log "  No project-level .mcp.json found."
  log "  Either copy framework/config/mcp.json to .mcp.json or add these servers"
  log "  to your Claude Code settings: serena, ast-grep."
fi

# 4. Dependency graph -------------------------------------------------------
log "Step 4/8: dependency graph (dep-graph.sh)"
bash "$FRAMEWORK_ROOT/skills/dep-graph.sh" "$PROJECT_ROOT" \
  > "$FRAMEWORK_ROOT/index/depgraph.json" \
  || log "  WARN: dep-graph.sh returned non-zero; inventory will note this"
log "  -> framework/index/depgraph.json"

# 5-7. LLM agents (prepare instructions) ------------------------------------
log "Step 5/8: run the inventory agent from Claude Code"
cat <<EOF
  Prompt:
    Read framework/core/agents/inventory.md and execute it.
    Inputs are framework/index/structural.json and framework/index/depgraph.json.
    Produce framework/index/inventory.json and print INVENTORY_OK.
EOF

log "Step 6/8: run the decompose agent"
cat <<EOF
  Prompt:
    Read framework/core/agents/decompose.md and execute it.
    Input is framework/index/inventory.json.
    Produce framework/index/modules.json and print DECOMPOSE_OK.
EOF

log "Step 7/8: run the docgen agent"
cat <<EOF
  Prompt:
    Read framework/core/agents/docgen.md and execute it.
    Inputs are framework/index/inventory.json and framework/index/modules.json.
    Produce the root CLAUDE.md plus a CLAUDE.md for each module. Print DOCGEN_OK.
EOF

# 8. Baseline sha ----------------------------------------------------------
log "Step 8/8: record baseline git sha (after agents finish, rerun this script"
log "          with --finalize, or execute the command below manually)"
if [ "${1:-}" = "--finalize" ]; then
  head_sha="$(git rev-parse HEAD)"
  echo "$head_sha" > "$FRAMEWORK_ROOT/.last-run"
  log "  Recorded $head_sha in framework/.last-run"
else
  echo "  git rev-parse HEAD > framework/.last-run"
fi

log "init done. Next: run the three agents listed above inside Claude Code."
