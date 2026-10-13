#!/usr/bin/env bash
# Routing decisions only, through the meta-harness Harbor agent with the basic router: for each task Harbor starts the
# task's container and runs agent setup only (--install-only), where the agent makes one Luna call with the rules-only
# prompt (router/basic_system_prompt.txt) and saves agent/route.json. route_only=true skips installing the chosen
# harness; the task is never run and no tests run. Each decision is appended to study/basic_routes.csv and sent to
# Langfuse as one route-task trace.
#
# usage: study/route_basic.sh <task> [task ...]
#        study/route_basic.sh --all [task-list]      (default list study/final_tasks_all.txt, 89 tasks)
#   about $0.001 per task (one Luna call) and 10-60 s (container start; the first start of a task pulls its image)
#   Resumable: tasks that already have a decision in study/basic_routes.csv are skipped, and a task whose run left no
#   decision is retried once at the end of the pass. Run one copy at a time (parallel image pulls make Docker fail).
#   DRY_RUN=1          print the Harbor commands only (no calls, no containers)
#   PRUNE_BELOW_GB=20  remove unused Docker images when free disk drops below this
set -uo pipefail
cd "$(dirname "$0")/.."

[ $# -ge 1 ] || { sed -n 8,12p "$0"; exit 1; }
if [ "$1" = --all ]; then
  LIST="${2:-study/final_tasks_all.txt}"
  TASKS=$(sed 's/#.*//' "$LIST" | awk 'NF')
else
  TASKS="$*"
fi
MODEL="openrouter/openai/gpt-5.6-luna"
CSV="study/basic_routes.csv"
PRUNE_BELOW_GB="${PRUNE_BELOW_GB:-20}"
OBS_PY="${LANGFUSE_OBS_PYTHON:-$HOME/.venvs/ilab-obs/bin/python}"
export PYTHONPATH="$PWD/router${PYTHONPATH:+:$PYTHONPATH}"

if [ "${DRY_RUN:-0}" != 1 ]; then
  [ -f .env ] || { echo "no .env: copy .env.example to .env and fill it in"; exit 1; }
  set -a; . ./.env; set +a
  docker info >/dev/null 2>&1 || { echo "Docker is not running"; exit 1; }
fi
mkdir -p study/logs

decided() {  # the task already has a decision in the CSV
  [ -f "$CSV" ] && python3 -c 'import csv,sys; sys.exit(0 if any(r["task"] == sys.argv[2] and r["harness"] for r in csv.DictReader(open(sys.argv[1]))) else 1)' "$CSV" "$1"
}

PASSES="$TASKS $TASKS"
[ "${DRY_RUN:-0}" = 1 ] && PASSES="$TASKS"
for TASK in $PASSES; do
  if [ "${DRY_RUN:-0}" != 1 ] && decided "$TASK"; then continue; fi
  JOB="route-basic-$TASK-$(date +%Y%m%d-%H%M%S)"
  CMD=(harbor run -t "terminal-bench/$TASK" --model "$MODEL" --agent meta_harness:MetaHarness
       --ak router=basic --ak route_only=true --install-only --job-name "$JOB")
  if [ "${DRY_RUN:-0}" = 1 ]; then printf 'would run:'; printf ' %q' "${CMD[@]}"; echo; continue; fi
  if [ "$(df -Pk . | awk 'NR==2 {print int($4 / 1048576)}')" -lt "$PRUNE_BELOW_GB" ]; then
    docker image prune -af >/dev/null 2>&1
  fi
  "${CMD[@]}" > "study/logs/$JOB.log" 2>&1
  URL=""
  if [ -x "$OBS_PY" ] && [ -n "${LANGFUSE_PUBLIC_KEY:-}" ] && [ -n "${LANGFUSE_SECRET_KEY:-}" ]; then
    URL=$("$OBS_PY" study/langfuse_export.py "jobs/$JOB" --route-only 2>>"study/logs/$JOB.log" | tail -1)
  fi
  python3 - "$JOB" "$TASK" "$CSV" "$URL" <<'PY'
import csv, glob, json, os, sys
job, task, out, url = sys.argv[1:5]
f = glob.glob(f"jobs/{job}/*__*/agent/route.json")
d = json.load(open(f[0])) if f else {}
m = d.get("task_meta") or {}
row = {"routed_at": d.get("routed_at"), "task": task, "harness": d.get("harness"), "rule": d.get("rule"),
       "reason": d.get("reason") or ("" if f else "no decision: see study/logs/" + job + ".log"),
       "category": m.get("category"), "difficulty": m.get("difficulty"), "agent_minutes": m.get("agent_minutes"),
       "router": d.get("router"), "router_model": d.get("underlying_model"),
       "system_prompt_sha256": d.get("system_prompt_sha256"), "tokens_in": (d.get("tokens") or {}).get("in"),
       "tokens_out": (d.get("tokens") or {}).get("out"), "cost_usd": d.get("cost"), "seconds": d.get("seconds"),
       "byok": d.get("byok"), "job": job, "langfuse": url if url.startswith("http") else ""}
new = not os.path.exists(out)
with open(out, "a", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(row))
    if new:
        w.writeheader()
    w.writerow(row)
print(f"{task:40} -> {row['harness'] or 'NO DECISION':15} rule {row['rule']}  {row['reason'][:90]}")
PY
done
[ "${DRY_RUN:-0}" = 1 ] || echo "decisions appended to $CSV"
