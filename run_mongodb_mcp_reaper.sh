#!/usr/bin/env bash
#
# run_mongodb_mcp_reaper.sh — reap orphaned mongodb-mcp-server processes.
#
# Each Claude Code session spawns a `npm exec mongodb-mcp-server` triplet
# (npm -> sh -> node). These are NOT reaped when the session exits, so they
# accumulate at ~110 MB each and eventually push the 7.8 GB box into swap.
#
# "Stale" = a mongodb-mcp-server node process with NO live `claude` ancestor
# in its parent chain. A live session's server always chains up to its claude
# process; once the session ends, claude dies and the triplet is orphaned
# (reparented away from claude). This signal is age-independent and can never
# kill the server of a running session. The MIN_AGE floor is belt-and-suspenders
# against a server still mid-startup whose parent chain isn't wired yet.
#
# Silent on a healthy box; logs only when it actually reaps something.
# Modeled on run_ibgw_watchdog.sh.

set -uo pipefail

LOG="/root/BlueHorseshoe/src/logs/mcp_reaper.log"
MIN_AGE_SECS=600          # don't touch anything younger than 10 min
PATTERN='node .*mongodb-mcp-server'

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

# Does pid (or any ancestor) belong to a live `claude` process?
has_claude_ancestor() {
    local pid="$1" guard=0
    while [[ -n "$pid" && "$pid" != "0" && "$pid" != "1" ]]; do
        # guard against pathological loops
        (( guard++ > 64 )) && return 1
        local args ppid
        args=$(ps -o args= -p "$pid" 2>/dev/null) || return 1
        # match the claude CLI, not this reaper or an editor with "claude" in a path
        if [[ "$args" == claude* || "$args" == *"/claude "* || "$args" == *"/.bin/claude"* ]]; then
            return 0
        fi
        ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
        [[ -z "$ppid" || "$ppid" == "$pid" ]] && return 1
        pid="$ppid"
    done
    return 1
}

reaped=0
# Iterate candidate node mongodb-mcp-server processes.
while read -r pid age; do
    [[ -z "$pid" ]] && continue
    (( age < MIN_AGE_SECS )) && continue        # too young, skip
    if has_claude_ancestor "$pid"; then
        continue                                # live session, leave it
    fi
    if kill "$pid" 2>/dev/null; then
        echo "$(ts) reaped stale mcp-server node pid=$pid age=${age}s" >> "$LOG"
        (( reaped++ ))
    fi
done < <(ps -eo pid=,etimes=,args= | awk -v p="mongodb-mcp-server" '
    $0 ~ /node/ && $0 ~ p { print $1, $2 }')

# Reap orphaned wrappers (`npm exec ...` / `sh -c mongodb-mcp-server`) that no
# longer have any child — their node child is gone.
while read -r pid; do
    [[ -z "$pid" ]] && continue
    if ! pgrep -P "$pid" >/dev/null 2>&1; then
        if kill "$pid" 2>/dev/null; then
            echo "$(ts) reaped orphaned mcp-server wrapper pid=$pid" >> "$LOG"
            (( reaped++ ))
        fi
    fi
done < <(pgrep -f 'mongodb-mcp-server' | while read -r p; do
            a=$(ps -o args= -p "$p" 2>/dev/null)
            [[ "$a" == npm\ exec* || "$a" == sh\ -c\ mongodb-mcp-server* ]] && echo "$p"
         done)

exit 0
