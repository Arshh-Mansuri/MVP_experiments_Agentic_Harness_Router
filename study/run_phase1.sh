#!/usr/bin/env bash
# Phase 1 of STUDY_PLAN.md: run every queued (task, harness, repeat) on Harbor with the model fixed to Luna.
#
# usage: study/run_phase1.sh [queue_file]          (default study/phase1_queue.txt)
#   PARALLEL=3      runs at once
#   MAX_RETRIES=2   reruns of a slot whose earlier attempts produced no reward (infrastructure failure)
#   DRY_RUN=1       print what would run
#   MIN_CREDIT=0.5  stop launching runs when the OpenRouter key has less than this many dollars left
#   PRUNE_BELOW_GB=20  remove unused Docker images when free disk space drops below this (task images pile up)
#   MIN_FREE_GB=6   stop launching runs when free disk space is still below this after pruning
#
# Safe to rerun: a slot is skipped once any of its attempts has a reward.
set -euo pipefail
cd "$(dirname "$0")/.."

QUEUE="${1:-study/phase1_queue.txt}"
export PARALLEL="${PARALLEL:-3}" MAX_RETRIES="${MAX_RETRIES:-2}" DRY_RUN="${DRY_RUN:-0}" MIN_CREDIT="${MIN_CREDIT:-0.5}"
export PRUNE_BELOW_GB="${PRUNE_BELOW_GB:-20}" MIN_FREE_GB="${MIN_FREE_GB:-6}"
export MODEL="openrouter/openai/gpt-5.6-luna"
export LOG_DIR="study/logs"
mkdir -p "$LOG_DIR"

set -a; . ./.env; set +a
export OPENROUTER_API_KEY
docker info >/dev/null 2>&1 || { echo "Docker is not running"; exit 1; }

has_reward() {  # $1 = job dir; true if any trial in it has a verifier reward
  python3 - "$1" <<'PY'
import glob, json, sys
for f in glob.glob(f"{sys.argv[1]}/*__*/result.json"):
    r = json.load(open(f))
    if ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward") is not None:
        sys.exit(0)
sys.exit(1)
PY
}

credit_ok() {  # stop launching runs once the OpenRouter key is nearly out of credit
  local left
  left=$(curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY" |
    python3 -c "import json,sys; r=json.load(sys.stdin)['data'].get('limit_remaining'); print(9999 if r is None else r)" 2>/dev/null) || return 0
  python3 -c "import sys; sys.exit(0 if float('${left:-9999}') >= float('$MIN_CREDIT') else 1)"
}

free_gb() { df -g / | awk 'NR==2 {print $4}'; }

disk_ok() {  # prune unused Docker images when space is low; false if still below MIN_FREE_GB
  if [ "$(free_gb)" -lt "$PRUNE_BELOW_GB" ]; then
    echo "prune ($(free_gb) GB free)"
    docker image prune -af >/dev/null 2>&1; docker builder prune -af >/dev/null 2>&1
  fi
  [ "$(free_gb)" -ge "$MIN_FREE_GB" ]
}

run_slot() {  # $1 task, $2 harness, $3 repeat
  local task="$1" harness="$2" rep="$3" base="p1-$2-$1-r$3" job attempt=0
  if [ -e "$LOG_DIR/STOP_LOW_CREDIT" ] || { [ "$DRY_RUN" != 1 ] && ! credit_ok; }; then
    touch "$LOG_DIR/STOP_LOW_CREDIT"; echo "stop  $base (OpenRouter credit below \$$MIN_CREDIT)"; return 0
  fi
  if [ "$DRY_RUN" != 1 ] && ! disk_ok; then
    echo "stop  $base (only $(free_gb) GB free disk after pruning)"; return 0
  fi
  for d in jobs/"$base" jobs/"$base"-retry*; do
    [ -d "$d" ] || continue
    if has_reward "$d"; then echo "skip  $base (done)"; return 0; fi
    attempt=$((attempt + 1))
  done
  if [ "$attempt" -gt "$MAX_RETRIES" ]; then echo "give up $base ($attempt attempts without reward)"; return 0; fi
  job="$base"; [ "$attempt" -gt 0 ] && job="$base-retry$attempt"
  if [ "$DRY_RUN" = 1 ]; then echo "would run $job"; return 0; fi
  echo "start $job"
  harbor run -t "terminal-bench/$task" --model "$MODEL" --agent "$harness" --job-name "$job" \
    >"$LOG_DIR/$job.log" 2>&1 || true
  if has_reward "jobs/$job"; then echo "done  $job"; else echo "fail  $job (no reward, will retry on next pass)"; fi
}
export -f has_reward credit_ok free_gb disk_ok run_slot
rm -f "$LOG_DIR/STOP_LOW_CREDIT"

grep -v '^\s*$' "$QUEUE" | caffeinate -i xargs -P "$PARALLEL" -L 1 bash -c 'run_slot "$0" "$1" "$2"'

echo
# Progress only: printing pass rates here would expose the sealed test set.
done_slots=0; total_slots=0
while read -r task harness rep; do
  [ -n "$task" ] || continue
  total_slots=$((total_slots + 1))
  for d in jobs/"p1-$harness-$task-r$rep" jobs/"p1-$harness-$task-r$rep"-retry*; do
    if [ -d "$d" ] && has_reward "$d"; then done_slots=$((done_slots + 1)); break; fi
  done
done < "$QUEUE"
echo "Slots with a reward: $done_slots / $total_slots. Score with: python3 study/analyze_phase1.py"
