#!/usr/bin/env bash
# dep-graph.sh — per-language dependency graphs.
#
# Two graph families are produced, in separate top-level keys:
#
#   import_graphs   - file-to-file / module-to-module edges within the
#                     project. This is what decompose / context-loader
#                     use to compute module depends_on / depended_by.
#
#   package_graphs  - manifest-level dependency trees (third-party deps
#                     declared in Cargo.toml, requirements/pyproject,
#                     CMake linkage). Useful for the architecture
#                     reviewer (new external dependency? supply-chain
#                     audit?) but NOT a substitute for import edges.
#
# Output on stdout:
#
#   {
#     "root": "<abs path>",
#     "languages":      ["typescript", "python", ...],
#     "import_graphs":  { "<lang>": { tool, nodes, edges, raw } },
#     "package_graphs": { "<lang>": { tool, nodes, edges, raw } },
#     "errors":         [ "human-readable messages" ]
#   }
#
# The skill never hard-fails a language; it records an entry in `errors`
# instead so callers can use whichever graphs succeeded.

set -uo pipefail

ROOT="${1:-$(pwd)}"
ROOT="$(cd "$ROOT" && pwd)"
cd "$ROOT" || { echo "dep-graph: cannot cd into $ROOT" >&2; exit 2; }

command -v jq      >/dev/null 2>&1 || { echo "dep-graph: jq required"     >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "dep-graph: python3 required" >&2; exit 2; }

FWROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KLC_DIR="$ROOT/.klc"
RESOLVE="python3 $FWROOT/core/skills/profile-resolve.py"
DISCOVERY_MODE="$($RESOLVE --field module_discovery | python3 -c 'import json,sys;print(json.load(sys.stdin).get("mode",""))')"
PROFILE_EXCLUDES="$($RESOLVE --field excludes-regex)"
# Package graphs (pipdeptree/cargo metadata/cmake --graphviz) are opt-in.
# Decompose only needs import_graphs; package graphs are dead weight until
# a reviewer starts consuming them. Profiles enable with:
#   collect_package_graphs: true
COLLECT_PACKAGES="$($RESOLVE --field collect_package_graphs 2>/dev/null || echo false)"
BASELINE_RE='(^|/)(\.git|\.klc|node_modules|\.venv|venv|__pycache__|target|build|dist|out|bin|obj|\.gradle|\.idea|\.vs|\.next|\.cache|\.serena-cache)(/|$)'
if [ -n "$PROFILE_EXCLUDES" ]; then
  EXCLUDES_RE="$BASELINE_RE|$PROFILE_EXCLUDES"
else
  EXCLUDES_RE="$BASELINE_RE"
fi

errors_json="[]"
import_json="{}"
package_json="{}"
langs_json="[]"

add_error() { errors_json=$(jq --arg m "$1" '. + [$m]' <<<"$errors_json"); }

add_import() {
  local lang="$1" tool="$2" nodes="$3" edges="$4" raw="${5:-null}"
  import_json=$(jq --arg lang "$lang" --arg tool "$tool" \
                   --argjson n "$nodes" --argjson e "$edges" --argjson r "$raw" \
                   '. + {($lang): {tool: $tool, nodes: $n, edges: $e, raw: $r}}' \
                   <<<"$import_json")
  langs_json=$(jq --arg l "$lang" 'if index($l) then . else . + [$l] end' <<<"$langs_json")
}

add_package() {
  local lang="$1" tool="$2" nodes="$3" edges="$4" raw="${5:-null}"
  package_json=$(jq --arg lang "$lang" --arg tool "$tool" \
                    --argjson n "$nodes" --argjson e "$edges" --argjson r "$raw" \
                    '. + {($lang): {tool: $tool, nodes: $n, edges: $e, raw: $r}}' \
                    <<<"$package_json")
  langs_json=$(jq --arg l "$lang" 'if index($l) then . else . + [$l] end' <<<"$langs_json")
}

# ---- Import graphs for python/rust/typescript via our own scanner -----------
# The skill reads structural.json to find source_roots; if inventory/scanner
# hasn't run yet we skip and record a note. This scanner handles project-
# internal imports only; third-party imports naturally fall out (not in
# source_roots).
if [ -f "$KLC_DIR/index/structural.json" ]; then
  if ig=$(python3 "$FWROOT/core/skills/import-graph.py" 2>/dev/null); then
    for lang in python rust typescript; do
      entry=$(jq --arg l "$lang" '.[$l] // null' <<<"$ig")
      if [ "$entry" != "null" ]; then
        nodes=$(jq '.nodes' <<<"$entry")
        edges=$(jq '.edges' <<<"$entry")
        add_import "$lang" "import-graph.py" "$nodes" "$edges"
      fi
    done
  else
    add_error "import-graph: scanner failed; import edges for python/rust/typescript unavailable"
  fi
else
  add_error "import-graph: structural.json missing; run file-scanner.sh first for import edges"
fi

# ---- TypeScript madge (import graph, richer than our own scanner) -----------
# If madge is installed we overwrite the typescript import-graph with its
# output — madge resolves tsconfig paths and commonjs require() that our
# simple scanner misses.
if [ -f "$ROOT/package.json" ] && command -v madge >/dev/null 2>&1; then
  target="src"; [ -d "$ROOT/src" ] || target="."
  if raw=$(madge --json "$target" 2>/dev/null); then
    nodes="[]"; edges="[]"
    while IFS= read -r file; do
      nodes=$(jq --arg id "$file" --arg p "$file" '. + [{id: $id, path: $p}]' <<<"$nodes")
    done < <(jq -r 'keys[]' <<<"$raw")
    while IFS= read -r pair; do
      from=$(jq -r '.from' <<<"$pair")
      to=$(jq -r '.to'   <<<"$pair")
      edges=$(jq --arg f "$from" --arg t "$to" '. + [{from: $f, to: $t}]' <<<"$edges")
    done < <(jq -c 'to_entries[] | . as $e | $e.value[] | {from: $e.key, to: .}' <<<"$raw")
    add_import "typescript" "madge" "$nodes" "$edges" "$raw"
  fi
fi

# ---- Package graphs (opt-in) ------------------------------------------------
if [ "$COLLECT_PACKAGES" = "true" ]; then

# Python: pipdeptree (manifest-level).
if [ -f "$ROOT/pyproject.toml" ] || [ -f "$ROOT/setup.py" ] || [ -f "$ROOT/requirements.txt" ]; then
  if command -v pipdeptree >/dev/null 2>&1; then
    if raw=$(pipdeptree --json 2>/dev/null); then
      nodes="[]"; edges="[]"
      while IFS= read -r pkg; do
        nodes=$(jq --arg id "$pkg" '. + [{id: $id, path: ""}]' <<<"$nodes")
      done < <(jq -r '.[].package.key' <<<"$raw")
      while IFS= read -r pair; do
        from=$(jq -r '.from' <<<"$pair")
        to=$(jq -r '.to'   <<<"$pair")
        edges=$(jq --arg f "$from" --arg t "$to" '. + [{from: $f, to: $t}]' <<<"$edges")
      done < <(jq -c '.[] | .package.key as $p | .dependencies[]? | {from: $p, to: .key}' <<<"$raw")
      add_package "python" "pipdeptree" "$nodes" "$edges" "$raw"
    else
      add_error "python: pipdeptree failed (is the venv active?)"
    fi
  else
    add_error "python: pipdeptree not installed (skipping package graph)"
  fi
fi

# Rust: cargo metadata (manifest-level).
if [ -f "$ROOT/Cargo.toml" ]; then
  if command -v cargo >/dev/null 2>&1; then
    if raw=$(cargo metadata --format-version 1 --no-deps 2>/dev/null); then
      nodes="[]"; edges="[]"
      while IFS= read -r pkg; do
        id=$(jq -r '.id'               <<<"$pkg")
        path=$(jq -r '.manifest_path'  <<<"$pkg")
        nodes=$(jq --arg id "$id" --arg p "$path" '. + [{id: $id, path: $p}]' <<<"$nodes")
        while IFS= read -r dep; do
          to=$(jq -r '.name' <<<"$dep")
          edges=$(jq --arg f "$id" --arg t "$to" '. + [{from: $f, to: $t}]' <<<"$edges")
        done < <(jq -c '.dependencies[]?' <<<"$pkg")
      done < <(jq -c '.packages[]' <<<"$raw")
      add_package "rust" "cargo metadata" "$nodes" "$edges" "$raw"
    else
      add_error "rust: cargo metadata failed"
    fi
  else
    add_error "rust: cargo not installed"
  fi
fi

# C/C++ generic: cmake --graphviz (manifest-level target linkage).
if [ -f "$ROOT/CMakeLists.txt" ] && command -v cmake >/dev/null 2>&1; then
  tmpdir="$(mktemp -d 2>/dev/null || mktemp -d -t cmake-graphviz)"
  if cmake -S "$ROOT" -B "$tmpdir" --graphviz="$tmpdir/deps.dot" >/dev/null 2>&1; then
    dot_file="$tmpdir/deps.dot"
    if [ -f "$dot_file" ]; then
      nodes="[]"; edges="[]"
      while IFS= read -r line; do
        if [[ "$line" =~ \"node[0-9]+\"[[:space:]]*\[[[:space:]]*label[[:space:]]*=[[:space:]]*\"([^\"]+)\" ]]; then
          nodes=$(jq --arg id "${BASH_REMATCH[1]}" '. + [{id: $id, path: ""}]' <<<"$nodes")
        fi
      done < "$dot_file"
      raw=$(jq -Rs . <"$dot_file")
      add_package "cpp" "cmake --graphviz" "$nodes" "$edges" "$raw"
    else
      add_error "cpp: cmake produced no graphviz output"
    fi
  else
    add_error "cpp: cmake configure failed (project may need custom options)"
  fi
  rm -rf "$tmpdir"
fi

fi  # COLLECT_PACKAGES

# ---- Build.cs module graph for UE (import graph — modules linked to each
# other, not package-level). Only when the profile explicitly opts in. -------
UPROJECT=""
if [ "$DISCOVERY_MODE" = "build-cs" ]; then
  if ls "$ROOT"/*.uproject >/dev/null 2>&1; then
    UPROJECT="$(ls "$ROOT"/*.uproject | head -1)"
  elif ls "$ROOT"/*/*.uproject >/dev/null 2>&1; then
    UPROJECT="$(ls "$ROOT"/*/*.uproject | head -1)"
  fi
fi
if [ -n "$UPROJECT" ]; then
  nodes="[]"; edges="[]"
  declare -A ue_seen=()
  uproject_dir="$(dirname "$UPROJECT")"
  while IFS= read -r build_cs; do
    [ -z "$build_cs" ] && continue
    mod_name="$(basename "$build_cs" .Build.cs)"
    rel_path="${build_cs#$ROOT/}"
    if [ -z "${ue_seen[$mod_name]+x}" ]; then
      ue_seen[$mod_name]=1
      nodes=$(jq --arg id "$mod_name" --arg p "$rel_path" '. + [{id: $id, path: $p}]' <<<"$nodes")
    fi
    # Extract dependency module names. Build.cs files use four variants:
    #   - PublicDependencyModuleNames.AddRange(new string[] { "Foo", "Bar" })
    #   - PublicDependencyModuleNames.Add("Foo")
    #   - PrivateDependencyModuleNames.AddRange(...)
    #   - Public/PrivateIncludePathModuleNames.*
    # Use python for a robust multi-line-aware parse.
    deps="$(python3 - "$build_cs" <<'PY'
import re, sys
src = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
src = re.sub(r"//[^\n]*", "", src)
names = set()
for m in re.finditer(
    r"(Public|Private)(Dependency|IncludePath)ModuleNames\s*\.\s*(Add|AddRange)\s*\(",
    src,
):
    i = m.end(); depth = 1
    while i < len(src) and depth > 0:
        c = src[i]
        if c == "(": depth += 1
        elif c == ")": depth -= 1
        i += 1
    block = src[m.end():i-1]
    for s in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', block):
        names.add(s)
for n in sorted(names):
    print(n)
PY
)"
    while IFS= read -r dep; do
      [ -z "$dep" ] && continue
      if [ -z "${ue_seen[$dep]+x}" ]; then
        ue_seen[$dep]=1
        nodes=$(jq --arg id "$dep" '. + [{id: $id, path: ""}]' <<<"$nodes")
      fi
      edges=$(jq --arg f "$mod_name" --arg t "$dep" '. + [{from: $f, to: $t}]' <<<"$edges")
    done <<<"$deps"
  done < <(
    {
      find "$uproject_dir/Source" -type f -name "*.Build.cs" 2>/dev/null
      find "$uproject_dir/Plugins" -type f -name "*.Build.cs" 2>/dev/null
      find "$ROOT/Plugins"         -type f -name "*.Build.cs" 2>/dev/null
    } | grep -Ev "$EXCLUDES_RE" | sort -u
  )
  raw_uproject=$(jq -Rs . <<<"$UPROJECT")
  add_import "cpp-unreal" "grep *.Build.cs" "$nodes" "$edges" "$raw_uproject"
fi

jq -n \
  --arg    root "$ROOT" \
  --argjson languages      "$langs_json" \
  --argjson import_graphs  "$import_json" \
  --argjson package_graphs "$package_json" \
  --argjson errors         "$errors_json" \
  '{
    root:            $root,
    languages:       $languages,
    import_graphs:   $import_graphs,
    package_graphs:  $package_graphs,
    errors:          $errors
  }'
