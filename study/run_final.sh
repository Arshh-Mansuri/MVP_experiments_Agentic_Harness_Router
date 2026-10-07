#!/usr/bin/env bash
# The final run: every task in a list goes through study/run_live_router.sh with Luna as the router and Luna doing
# the task. Each run is traced, recorded in study/live_runs.jsonl and uploaded to Langfuse.
#
# usage: study/run_final.sh [task-list] [batch]
#   task-list  default study/final_tasks_all.txt (also: final_tasks_unseen.txt, final_tasks_seen.txt)
#   batch      default 'final'; job folders are jobs/live-<batch>-luna-<task>-<time>, Langfuse tag batch:<batch>
#
#   PARALLEL=3         tasks at once (Phase 1 also ran 3 at once)
#   MAX_RETRIES=1      extra attempts for a task that ends with no reward (Harbor or Docker failed before scoring)
#   MIN_CREDIT=0.5     stop launching tasks when the OpenRouter key has less than this many dollars left (0 = off)
#   PRUNE_BELOW_GB=20  remove unused Docker images when free disk drops below this (task images pile up)
#   MIN_FREE_GB=6      stop launching tasks when free disk is still below this after pruning
#   DRY_RUN=1          route and print the Harbor commands only (tasks not in the table still cost one Luna call)
#   touch study/logs/STOP   stop launching new tasks; running ones finish. Delete the file before the next run.
#
# Resumable: a task already scored (reward not null) in this batch is skipped, so after a crash, Ctrl-C or a reboot
# run the same command again. Each task's console output goes to study/logs/<batch>-console/<task>.out.
set -uo pipefail
cd "$(dirname "$0")/.."

LIST="${1:-study/final_tasks_all.txt}"
export BATCH="${2:-final}"
export PARALLEL="${PARALLEL:-3}" MAX_RETRIES="${MAX_RETRIES:-1}" MIN_CREDIT="${MIN_CREDIT:-0.5}"
export PRUNE_BELOW_GB="${PRUNE_BELOW_GB:-20}" MIN_FREE_GB="${MIN_FREE_GB:-6}" DRY_RUN="${DRY_RUN:-0}"
export CONSOLE="study/logs/$BATCH-console"
[ -f "$LIST" ] || { echo "no task list at $LIST"; exit 1; }
[ -f .env ] || { echo "no .env: copy .env.example to .env and fill it in"; exit 1; }
set -a; . ./.env; set +a
docker info >/dev/null 2>&1 || { echo "Docker is not running"; exit 1; }
[ -e study/logs/STOP ] && { echo "study/logs/STOP exists: delete it to start"; exit 1; }
mkdir -p "$CONSOLE"

reward() {  # latest reward of $1 in this batch, empty if none
  python3 - "$BATCH" "$1" <<'PY'
import json, os, sys
last = None
if os.path.exists("study/live_runs.jsonl"):
    for line in open("study/live_runs.jsonl"):
        r = json.loads(line)
        if r.get("batch") == sys.argv[1] and r.get("task") == sys.argv[2] and r.get("reward") is not None:
            last = r["reward"]
print("" if last is None else last)
PY
}

credit_ok() {
  [ "$MIN_CREDIT" = 0 ] && return 0
  local left
  left=$(curl -s --max-time 20 https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY" |
    python3 -c "import json,sys; r=json.load(sys.stdin)['data'].get('limit_remaining'); print(9999 if r is None else r)" 2>/dev/null) || return 0
  python3 -c "import sys; sys.exit(0 if float('${left:-9999}') >= float('$MIN_CREDIT') else 1)"
}

free_gb() { df -Pk . | awk 'NR==2 {print int($4 / 1048576)}'; }

disk_ok() {
  if [ "$(free_gb)" -lt "$PRUNE_BELOW_GB" ]; then
    echo "prune ($(free_gb) GB free)"
    docker image prune -af >/dev/null 2>&1; docker builder prune -af >/dev/null 2>&1
  fi
  [ "$(free_gb)" -ge "$MIN_FREE_GB" ]
}

run_task() {
  local t="$1" out="$CONSOLE/$1.out" attempt=0 r rc
  while :; do
    r=$(reward "$t")
    if [ -n "$r" ]; then
      [ "$attempt" = 0 ] && echo "skip  $t (already scored: $r)" || echo "done  $t reward=$r"
      return 0
    fi
    if [ "$attempt" -gt "$MAX_RETRIES" ]; then echo "give up $t ($attempt attempts without a reward; rerun to retry)"; return 0; fi
    if [ -e study/logs/STOP ]; then echo "stop  $t (study/logs/STOP)"; return 0; fi
    if [ "$DRY_RUN" != 1 ]; then
      credit_ok || { touch study/logs/STOP; echo "stop  $t (OpenRouter credit below \$$MIN_CREDIT; wrote study/logs/STOP)"; return 0; }
      disk_ok || { echo "stop  $t (only $(free_gb) GB free after pruning)"; return 0; }
    fi
    attempt=$((attempt + 1))
    echo "start $t$([ "$attempt" -gt 1 ] && echo " (retry $((attempt - 1)))")"
    study/run_live_router.sh "$t" luna >> "$out" 2>&1
    rc=$?
    if [ "$DRY_RUN" = 1 ]; then echo "dry   $t: $(grep -o 'agent [a-z0-9-]*' "$out" | tail -1)"; return 0; fi
    [ -z "$(reward "$t")" ] && echo "fail  $t (exit $rc, no reward; see $out)"
  done
}
export -f reward credit_ok free_gb disk_ok run_task

TASKS=$(grep -v '^[[:space:]]*#' "$LIST" | awk 'NF {print $1}')
echo "final run: $(printf '%s\n' "$TASKS" | grep -c .) tasks from $LIST, batch '$BATCH', $PARALLEL at a time," \
  "router luna, model luna"
KEEP_AWAKE=(); command -v caffeinate >/dev/null && KEEP_AWAKE=(caffeinate -i)
printf '%s\n' "$TASKS" | ${KEEP_AWAKE[@]+"${KEEP_AWAKE[@]}"} xargs -P "$PARALLEL" -n 1 bash -c 'run_task "$0"'

[ "$DRY_RUN" = 1 ] && exit 0
python3 - "$BATCH" "$LIST" <<'PY'
import json, os, sys
batch, tasks = sys.argv[1], [l.split()[0] for l in open(sys.argv[2]) if l.strip() and not l.lstrip().startswith("#")]
rows, cost = {}, 0.0
if os.path.exists("study/live_runs.jsonl"):
    for line in open("study/live_runs.jsonl"):
        r = json.loads(line)
        if r.get("batch") == batch and r["task"] in tasks:
            cost += (r.get("cost_usd") or 0) + (r.get("route_cost") or 0)
            if r.get("reward") is not None or r["task"] not in rows:
                rows[r["task"]] = r
scored = [r for r in rows.values() if r.get("reward") is not None]
passed = sum(1 for r in scored if r["reward"] >= 1)
print(f"\nbatch '{batch}': {len(scored)} of {len(tasks)} tasks scored, {passed} passed"
      f" ({passed / max(len(scored), 1):.0%}), ${cost:.3f} spent including retries")
missing = [t for t in tasks if t not in rows or rows[t].get("reward") is None]
if missing:
    print(f"{len(missing)} without a reward (rerun the same command to retry):", " ".join(missing))
PY
