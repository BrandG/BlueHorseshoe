#!/bin/bash
# Memory-confined launcher for heavy research / data-pull work.
#
# Why this exists: on 2026-07-06 an ad-hoc 1-minute-bar pull ballooned to ~5GB,
# exhausted the 7.8GB box, and the kernel OOM-killer reaped it. Because that
# process lived INSIDE the tmux-spawn systemd scope, systemd failed the whole
# scope and took tmux + Claude down with it (twice).
#
# This wrapper runs the command in its OWN transient systemd scope with a hard
# memory ceiling. If the work blows the cap, the cgroup OOM-killer kills ONLY
# this scope's processes -- global memory is never exhausted, and the scope is a
# sibling of the tmux scope (not a child), so the terminal survives. It also
# marks itself as the preferred global-OOM victim (OOMScoreAdjust) as a belt-
# and-suspenders backstop.
#
# Usage (mirrors run.sh -- same venv / PYTHONPATH / .env):
#   ./run_research.sh python research/opening_range_breakout_v1/pull_1min.py
#   MEM_MAX=6G ./run_research.sh python heavy_thing.py     # override the cap
#
# Defaults: hard cap 4.5G, soft throttle 3G, up to 2G of its own swap.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$REPO_DIR/.venv/bin/activate"
export PYTHONPATH="$REPO_DIR/src"
cd "$REPO_DIR"
if [ -f "$REPO_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO_DIR/.env"
fi

MEM_MAX="${MEM_MAX:-4500M}"     # hard ceiling: cgroup OOM-kills the scope past this
MEM_HIGH="${MEM_HIGH:-3G}"      # soft throttle: kernel reclaims/swaps before the hard kill
MEM_SWAP_MAX="${MEM_SWAP_MAX:-2G}"

if [ "$#" -eq 0 ]; then
  echo "usage: ./run_research.sh <command> [args...]" >&2
  exit 2
fi

echo "[run_research] confining to scope: MemoryHigh=$MEM_HIGH MemoryMax=$MEM_MAX MemorySwapMax=$MEM_SWAP_MAX" >&2
echo "[run_research] a breach kills THIS scope only; tmux/Claude are insulated." >&2

# Mark this process (and, by fork-inheritance, the research command) as the
# preferred victim if a GLOBAL OOM ever fires. OOMScoreAdjust can't be set as a
# --scope property (the caller spawns the process, not systemd), so we set it on
# ourselves before exec and let it inherit. Range is -1000..1000; 900 = "kill me
# first". Belt-and-suspenders behind the MemoryMax cgroup confinement below.
echo 900 > /proc/self/oom_score_adj 2>/dev/null || true

exec systemd-run \
  --scope \
  --quiet \
  --collect \
  --slice=research.slice \
  --unit="research-$$" \
  -p MemoryHigh="$MEM_HIGH" \
  -p MemoryMax="$MEM_MAX" \
  -p MemorySwapMax="$MEM_SWAP_MAX" \
  -- "$@"
