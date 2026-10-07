#!/usr/bin/env bash
# The final run: every task in a list goes through study/run_live_router.sh with Luna as the router and Luna doing
# the task. One task at a time; each run is traced, recorded in study/live_runs.jsonl and uploaded to Langfuse.
#
# usage: study/run_final.sh [task-list] [batch]
#   task-list  default study/final_tasks_all.txt (also: final_tasks_unseen.txt, final_tasks_seen.txt)
#   batch      default 'final'; job folders are jobs/live-<batch>-luna-<task>-<time>, Langfuse tag batch:<batch>
#
# Resumable: a task that already has a scored row (reward not null) for this batch in study/live_runs.jsonl is
# skipped, so after a crash, Ctrl-C or a reboot just run the same command again. Runs with no reward (Harbor or
# Docker failed before the verifier) are retried on the next invocation.
set -uo pipefail
cd "$(dirname "$0")/.."

LIST="${1:-study/final_tasks_all.txt}"
BATCH="${2:-final}"
[ -f "$LIST" ] || { echo "no task list at $LIST"; exit 1; }
TASKS=$(grep -v '^[[:space:]]*#' "$LIST" | awk 'NF {print $1}')
N=$(printf '%s\n' "$TASKS" | grep -c .)
KEEP_AWAKE=(); command -v caffeinate >/dev/null && KEEP_AWAKE=(caffeinate -i)

scored() {
  python3 - "$BATCH" <<'PY'
import json, os, sys
if os.path.exists("study/live_runs.jsonl"):
    for line in open("study/live_runs.jsonl"):
        r = json.loads(line)
        if r.get("batch") == sys.argv[1] and r.get("reward") is not None:
            print(r["task"])
PY
}

echo "final run: $N tasks from $LIST, batch '$BATCH', router luna, model luna"
i=0
for t in $TASKS; do
  i=$((i + 1))
  if scored | grep -qx "$t"; then echo "[$i/$N] $t: already scored in batch '$BATCH', skipping"; continue; fi
  echo; echo "========== [$i/$N] $t =========="
  BATCH="$BATCH" ${KEEP_AWAKE[@]+"${KEEP_AWAKE[@]}"} study/run_live_router.sh "$t" luna || echo "[$i/$N] $t: runner exited $?, continuing"
done

python3 - "$BATCH" <<'PY'
import json, sys
rows = {}
for line in open("study/live_runs.jsonl"):
    r = json.loads(line)
    if r.get("batch") == sys.argv[1]:
        rows[r["task"]] = r
scored = [r for r in rows.values() if r.get("reward") is not None]
passed = sum(1 for r in scored if r["reward"] >= 1)
cost = sum((r.get("cost_usd") or 0) + (r.get("route_cost") or 0) for r in rows.values())
print(f"\nbatch '{sys.argv[1]}': {len(rows)} tasks run, {len(scored)} scored, {passed} passed"
      f" ({passed / max(len(scored), 1):.0%}), ${cost:.3f} total")
unscored = sorted(t for t, r in rows.items() if r.get("reward") is None)
if unscored:
    print("no reward (rerun this command to retry):", " ".join(unscored))
PY
