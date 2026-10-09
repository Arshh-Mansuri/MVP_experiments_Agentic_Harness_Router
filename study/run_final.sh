#!/usr/bin/env bash
# The final run of the meta-harness: every task in a list is routed by Luna, run by Luna in the chosen harness
# (study/run_live_router.sh), and given one fallback attempt if the first attempt fails in a way visible at run time.
# Each run is traced, recorded in study/live_runs.jsonl and uploaded to Langfuse.
#
# Fallback (Project 16: "a fallback harness if the first attempt fails"): triggered only by run-time signals, the
# same ones study/fallback_sim.py simulates: no reward (Harbor or the harness produced no result), a crash
# (RuntimeError, NonZeroAgentExitCodeError, AgentSetupTimeoutError, APIError, VerifierTimeoutError) or the agent
# timing out (AgentTimeoutError). Never the hidden test result. The fallback reruns the same harness, with no
# routing call: offline, retrying the same harness recovered as much as switching (PROBLEM_DEFINITION.md, RQ3).
# A task's result is the fallback's if one ran, otherwise the first attempt's.
#
# usage: study/run_final.sh [task-list] [batch]
#   task-list  default study/final_tasks_all.txt (also: final_tasks_unseen.txt, final_tasks_seen.txt)
#   batch      default 'final'; job folders are jobs/live-<batch>-luna-<task>-<time>, Langfuse tag batch:<batch>
#
#   PARALLEL=3         tasks at once (Phase 1 also ran 3 at once)
#   MIN_CREDIT=0.5     stop launching runs when the OpenRouter key has less than this many dollars left (0 = off)
#   PRUNE_BELOW_GB=20  remove unused Docker images when free disk drops below this (task images pile up)
#   MIN_FREE_GB=6      stop launching runs when free disk is still below this after pruning
#   DRY_RUN=1          route and print the Harbor commands only (tasks not in the table still cost one Luna call)
#   touch study/logs/STOP   stop launching new runs; running ones finish. Delete the file before the next run.
#
# Resumable: rerun the same command after a crash, Ctrl-C or reboot. Finished tasks are skipped, and a task whose first
# attempt failed but has no fallback yet gets its fallback. Console output: study/logs/<batch>-console/<task>.out.
# Score the batch with: python3 study/final_results.py
set -uo pipefail
cd "$(dirname "$0")/.."

LIST="${1:-study/final_tasks_all.txt}"
export BATCH="${2:-final}"
export PARALLEL="${PARALLEL:-3}" MIN_CREDIT="${MIN_CREDIT:-0.5}"
export PRUNE_BELOW_GB="${PRUNE_BELOW_GB:-20}" MIN_FREE_GB="${MIN_FREE_GB:-6}" DRY_RUN="${DRY_RUN:-0}"
export CONSOLE="study/logs/$BATCH-console"
[ -f "$LIST" ] || { echo "no task list at $LIST"; exit 1; }
[ -f .env ] || { echo "no .env: copy .env.example to .env and fill it in"; exit 1; }
set -a; . ./.env; set +a
docker info >/dev/null 2>&1 || { echo "Docker is not running"; exit 1; }
[ -e study/logs/STOP ] && { echo "study/logs/STOP exists: delete it to start"; exit 1; }
mkdir -p "$CONSOLE"

state() {  # prints: run | fallback <harness> <first-job> <trigger> | done <reward or none> <first|fallback>
  python3 - "$BATCH" "$1" <<'PY'
import json, os, sys
CRASH = {"RuntimeError", "NonZeroAgentExitCodeError", "AgentSetupTimeoutError", "APIError", "VerifierTimeoutError"}
first = fb = None
if os.path.exists("study/live_runs.jsonl"):
    for line in open("study/live_runs.jsonl"):
        r = json.loads(line)
        if r.get("batch") == sys.argv[1] and r.get("task") == sys.argv[2]:
            if r.get("attempt") == "fallback":
                fb = r
            else:
                first = r
if fb:
    print("done", fb.get("reward"), "fallback")
elif first:
    why = ("no-reward" if first.get("reward") is None else "crash" if first.get("exception") in CRASH
           else "timeout" if first.get("exception") == "AgentTimeoutError" else None)
    print(f"fallback {first['harness']} {first['job']} {why}" if why else f"done {first.get('reward')} first")
else:
    print("run")
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
  local t="$1" out="$CONSOLE/$1.out" launched=0 s a b c before
  while :; do
    before=$(state "$t")
    read -r s a b c <<< "$before"
    if [ "$s" = done ]; then
      [ "$launched" = 0 ] && echo "skip  $t (already done: reward $a, $b attempt)" || echo "done  $t reward=$a ($b attempt)"
      return 0
    fi
    if [ -e study/logs/STOP ]; then echo "stop  $t (study/logs/STOP)"; return 0; fi
    if [ "$DRY_RUN" != 1 ]; then
      credit_ok || { touch study/logs/STOP; echo "stop  $t (OpenRouter credit below \$$MIN_CREDIT; wrote study/logs/STOP)"; return 0; }
      disk_ok || { echo "stop  $t (only $(free_gb) GB free after pruning)"; return 0; }
    fi
    launched=1
    if [ "$s" = run ]; then
      echo "start $t"
      study/run_live_router.sh "$t" luna >> "$out" 2>&1
    else
      echo "fallback $t: first attempt on $a ended in $c, retrying $a"
      FALLBACK_HARNESS="$a" FALLBACK_OF="$b" FALLBACK_TRIGGER="$c" study/run_live_router.sh "$t" luna >> "$out" 2>&1
    fi
    if [ "$DRY_RUN" = 1 ]; then echo "dry   $t: $(grep -o 'agent [a-z0-9-]*' "$out" | tail -1)"; return 0; fi
    if [ "$(state "$t")" = "$before" ]; then
      echo "fail  $t (the runner wrote no result; see $out, rerun to retry)"; return 0
    fi
  done
}
export -f state credit_ok free_gb disk_ok run_task

TASKS=$(grep -v '^[[:space:]]*#' "$LIST" | awk 'NF {print $1}')
echo "final run: $(printf '%s\n' "$TASKS" | grep -c .) tasks from $LIST, batch '$BATCH', $PARALLEL at a time," \
  "router luna, model luna, same-harness fallback"
KEEP_AWAKE=(); command -v caffeinate >/dev/null && KEEP_AWAKE=(caffeinate -i)
printf '%s\n' "$TASKS" | ${KEEP_AWAKE[@]+"${KEEP_AWAKE[@]}"} xargs -P "$PARALLEL" -n 1 bash -c 'run_task "$0"'

[ "$DRY_RUN" = 1 ] && exit 0
echo
python3 study/final_results.py --batch "$BATCH" --tasks "$LIST" --brief
