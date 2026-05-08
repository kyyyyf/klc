#!/usr/bin/env bash
# file-scanner.sh — profile-driven structural scan of a project.
#
# Usage:   file-scanner.sh [ROOT]    (ROOT defaults to CWD)
#
# Output:  JSON on stdout:
#   {
#     "root":           "<abs path>",
#     "profile":        "<active profile name>",
#     "total_files":    N,
#     "total_lines":    N,
#     "languages":      { "<lang>": { "files": N, "lines": N } },
#     "directory_tree": [ { "path": "src", "files": N } ],
#     "entry_points":   [ "<rel path>", ... ],
#     "source_roots":   [ { "path": "...", "module": "..." } ]
#   }
#
# Excludes, entry patterns, and module discovery mode come from the active
# profile's manifest.yml. See framework/profiles/<name>/manifest.yml.

set -uo pipefail

ROOT="${1:-$(pwd)}"
ROOT="$(cd "$ROOT" && pwd)"

command -v jq >/dev/null 2>&1 || { echo "file-scanner: jq required" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "file-scanner: python3 required" >&2; exit 2; }

FWROOT="$(cd "$(dirname "$0")/.." && pwd)"
# core/skills -> framework dir
FWROOT="$(cd "$FWROOT/.." && pwd)"
RESOLVE="python3 $FWROOT/core/skills/profile-resolve.py"

PROFILE="$($RESOLVE --field name)"
PROFILE_EXCLUDES="$($RESOLVE --field excludes-regex)"
# Baseline excludes always on; profile extends.
BASELINE_RE='(^|/)(\.git|node_modules|\.venv|venv|__pycache__|target|build|dist|out|bin|obj|\.gradle|\.idea|\.vs|\.next|\.cache|\.serena-cache|framework/index|framework/logs)(/|$)'
if [ -n "$PROFILE_EXCLUDES" ]; then
  EXCLUDES_RE="$BASELINE_RE|$PROFILE_EXCLUDES"
else
  EXCLUDES_RE="$BASELINE_RE"
fi

MODULE_DISCOVERY="$($RESOLVE --field module_discovery)"
DISCOVERY_MODE="$(echo "$MODULE_DISCOVERY" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("mode",""))')"
ENTRY_PATTERNS="$(echo "$MODULE_DISCOVERY" | python3 -c 'import json,sys;print("\n".join(json.load(sys.stdin).get("entry_patterns",[]) or []))')"

ext_lang() {
  case "$1" in
    py) echo python ;;
    ts|tsx) echo typescript ;;
    js|jsx|mjs|cjs) echo javascript ;;
    rs) echo rust ;;
    c|h) echo c ;;
    cc|cpp|cxx|hpp|hh|hxx) echo cpp ;;
    cs) echo csharp ;;
    java) echo java ;;
    kt|kts) echo kotlin ;;
    rb) echo ruby ;;
    php) echo php ;;
    swift) echo swift ;;
    uproject|uplugin) echo unreal ;;
    *) echo "" ;;
  esac
}

tmp_files="$(mktemp)"
trap 'rm -f "$tmp_files"' EXIT

find "$ROOT" -type f 2>/dev/null \
  | sed "s|^$ROOT/||" \
  | grep -Ev "$EXCLUDES_RE" > "$tmp_files" || true

total_files=$(wc -l < "$tmp_files" | tr -d ' ')
total_lines=0

declare -A lang_files
declare -A lang_lines
declare -A dir_files

while IFS= read -r rel; do
  [ -z "$rel" ] && continue
  ext="${rel##*.}"
  [ "$ext" = "$rel" ] && ext=""
  lang="$(ext_lang "$ext")"
  abs="$ROOT/$rel"
  if [ -n "$lang" ]; then
    lines=0
    [ -r "$abs" ] && lines=$(wc -l < "$abs" 2>/dev/null | tr -d ' ')
    lines=${lines:-0}
    lang_files[$lang]=$(( ${lang_files[$lang]:-0} + 1 ))
    lang_lines[$lang]=$(( ${lang_lines[$lang]:-0} + lines ))
    total_lines=$(( total_lines + lines ))
  fi
  top="${rel%%/*}"
  [ "$top" = "$rel" ] && top="."
  dir_files[$top]=$(( ${dir_files[$top]:-0} + 1 ))
done < "$tmp_files"

langs_json="{}"
for k in "${!lang_files[@]}"; do
  langs_json=$(jq --arg k "$k" --argjson f "${lang_files[$k]}" --argjson l "${lang_lines[$k]}" \
                '. + {($k): {files: $f, lines: $l}}' <<<"$langs_json")
done
dir_json="[]"
for k in "${!dir_files[@]}"; do
  dir_json=$(jq --arg p "$k" --argjson f "${dir_files[$k]}" '. + [{path: $p, files: $f}]' <<<"$dir_json")
done
dir_json=$(jq 'sort_by(-.files)' <<<"$dir_json")

# Entry points: project-file conventions (package.json, Cargo.toml, ...) plus
# profile-declared patterns (e.g. *.uproject, *.uplugin).
entries_json="[]"
for cand in package.json pyproject.toml setup.py Cargo.toml CMakeLists.txt meson.build Makefile \
            src/index.ts src/index.tsx src/index.js index.ts index.js \
            src/main.py main.py app.py __main__.py \
            src/main.rs src/lib.rs; do
  if [ -e "$ROOT/$cand" ]; then
    entries_json=$(jq --arg p "$cand" '. + [$p]' <<<"$entries_json")
  fi
done
while IFS= read -r pat; do
  [ -z "$pat" ] && continue
  while IFS= read -r hit; do
    [ -z "$hit" ] && continue
    rel="${hit#$ROOT/}"
    entries_json=$(jq --arg p "$rel" '. + [$p]' <<<"$entries_json")
  done < <(find "$ROOT" -type f -name "$pat" 2>/dev/null | grep -Ev "$EXCLUDES_RE" || true)
done <<<"$ENTRY_PATTERNS"

# Source roots.
source_roots_json="[]"
case "$DISCOVERY_MODE" in
  build-cs)
    declare -A seen=()
    while IFS= read -r bc; do
      [ -z "$bc" ] && continue
      rel="$(dirname "${bc#$ROOT/}")"
      mod="$(basename "$bc" .Build.cs)"
      key="$rel::$mod"
      if [ -z "${seen[$key]+x}" ]; then
        seen[$key]=1
        source_roots_json=$(jq --arg p "$rel" --arg n "$mod" \
                              '. + [{path: $p, module: $n}]' <<<"$source_roots_json")
      fi
    done < <(find "$ROOT" -type f -name "*.Build.cs" 2>/dev/null | grep -Ev "$EXCLUDES_RE" || true)
    ;;
  conventional-dirs | "")
    for cand in src lib pkg internal app apps services; do
      if [ -d "$ROOT/$cand" ]; then
        source_roots_json=$(jq --arg p "$cand" --arg n "$cand" \
                              '. + [{path: $p, module: $n}]' <<<"$source_roots_json")
      fi
    done
    ;;
  *)
    echo "file-scanner: unknown module_discovery.mode: $DISCOVERY_MODE" >&2
    exit 1
    ;;
esac

jq -n \
  --arg    root "$ROOT" \
  --arg    profile "$PROFILE" \
  --argjson tf  "$total_files" \
  --argjson tl  "$total_lines" \
  --argjson langs "$langs_json" \
  --argjson dirs  "$dir_json" \
  --argjson eps   "$entries_json" \
  --argjson srs   "$source_roots_json" \
  '{
     root:           $root,
     profile:        $profile,
     total_files:    $tf,
     total_lines:    $tl,
     languages:      $langs,
     directory_tree: $dirs,
     entry_points:   $eps,
     source_roots:   $srs
   }'
