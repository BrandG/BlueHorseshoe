#!/bin/bash
# Lint BlueHorseshoe Python. Run via ./run.sh ./lint.sh so PYTHONPATH=src is set.
#
# Usage:
#   ./lint.sh                      full tree (writes linting.txt) — CI / full sweep [slow]
#   ./lint.sh --changed [BASE]     only .py files changed vs BASE (default: master) [fast, local]
#   ./lint.sh bud                  one section: src/bud                              [fast]
#   ./lint.sh bud bh_ftmo          several sections
#   ./lint.sh src/bud/briefing.py  explicit file(s) / path(s)
#   ./lint.sh --list               show the available sections
#
# Sections are just the top-level dirs under src/ (bud, bh_ftmo, bluehorseshoe, bh_swing, ...).
set -uo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--list" ]; then
  echo "sections (dirs under src/):"
  for d in src/*/; do
    b=$(basename "$d")
    [ "$b" = "__pycache__" ] && continue
    [ -n "$(find "$d" -name '*.py' -print -quit 2>/dev/null)" ] && echo "  $b"
  done
  exit 0
fi

# --changed: lint only Python files touched vs BASE (committed-on-branch + staged + unstaged +
# untracked), restricted to src/. This is the local-change fast path.
if [ "${1:-}" = "--changed" ]; then
  base="${2:-master}"
  files=$( { git diff --name-only "$base"...HEAD 2>/dev/null
             git diff --name-only HEAD 2>/dev/null
             git ls-files --others --exclude-standard 2>/dev/null
           } | sort -u | grep -E '^src/.*\.py$' || true )
  if [ -z "$files" ]; then echo "no changed Python files under src/ (vs $base)"; exit 0; fi
  echo "linting changed files (vs $base):"; echo "$files" | sed 's/^/  /'
  # shellcheck disable=SC2086
  pylint $files
  exit $?
fi

# No args: full tree (preserves the original behavior + linting.txt report).
if [ "$#" -eq 0 ]; then
  date
  pylint $(find src -name "*.py") > linting.txt
  date
  echo "full report -> linting.txt"
  exit 0
fi

# Section names and/or explicit paths -> expand to a file list and lint to stdout.
files=()
for arg in "$@"; do
  if [ -f "$arg" ]; then
    files+=("$arg")
  elif [ -d "$arg" ]; then
    while IFS= read -r f; do files+=("$f"); done < <(find "$arg" -name '*.py')
  elif [ -d "src/$arg" ]; then
    while IFS= read -r f; do files+=("$f"); done < <(find "src/$arg" -name '*.py')
  else
    echo "unknown section/path: '$arg' (try ./lint.sh --list, a dir under src/, or a file path)" >&2
    exit 2
  fi
done
if [ "${#files[@]}" -eq 0 ]; then echo "no .py files matched"; exit 0; fi
pylint "${files[@]}"
