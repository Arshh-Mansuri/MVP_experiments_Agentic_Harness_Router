#!/usr/bin/env bash
# One live end-to-end run of the router (PROBLEM_DEFINITION.md step 8): choose a harness, then actually run it on
# Harbor with the model fixed to Luna and the harness version pinned. Everything else in the study is an offline
# replay of saved runs, so this is the check that the chosen harness really launches and scores.
#
# usage: study/run_live_router.sh <task> [router]
#   router defaults to 'lookup', which needs no API call: known tasks come from router/success_table.json, the rest
#   fall back to the Qwen hint and then to mini-swe-agent. Use jev-table or luna-table for the LLM router instead.
#   DRY_RUN=1 prints the decision and the Harbor command without running anything.
set -euo pipefail
cd "$(dirname "$0")/.."

TASK="${1:?usage: study/run_live_router.sh <task> [router]}"
ROUTER="${2:-lookup}"
export MODEL="openrouter/openai/gpt-5.6-luna"
V_TERMINUS2="${V_TERMINUS2:-2.0.0}"; V_MINI="${V_MINI:-2.4.6}"; V_PI="${V_PI:-1.0.1}"
mkdir -p study/logs

set -a; . ./.env; set +a; export OPENROUTER_API_KEY

if [ "$ROUTER" = "lookup" ]; then
  read -r HARNESS REASON <<<"$(TASK="$TASK" python3 - <<'PY'
import os, sys
sys.path.insert(0, "router")
import table_router
h, meta = table_router.lookup(os.environ["TASK"])
print(h, meta.get("reason", ""))
PY
)"
  ROUTE_COST=0
else
  HARNESS=$(router/.venv/bin/python router/pick_offline.py --router "$ROUTER" "$TASK" | tail -1)
  REASON="router call"
  ROUTE_COST=unknown
fi
case "$HARNESS" in
  terminus-2) VER="$V_TERMINUS2";; mini-swe-agent) VER="$V_MINI";; pi) VER="$V_PI";;
  *) echo "router '$ROUTER' returned '$HARNESS', which is not one of our three harnesses"; exit 1;;
esac

JOB="live-$ROUTER-$TASK-$(date +%Y%m%d-%H%M%S)"
echo "task      $TASK"
echo "router    $ROUTER (routing cost \$$ROUTE_COST)"
echo "harness   $HARNESS v$VER -- $REASON"
echo "model     $MODEL"
echo "job       $JOB"
CMD=(harbor run -t "terminal-bench/$TASK" --model "$MODEL" --agent "$HARNESS" --ak "version=$VER" --job-name "$JOB")
if [ "${DRY_RUN:-0}" = 1 ]; then printf 'would run:'; printf ' %q' "${CMD[@]}"; echo; exit 0; fi

docker info >/dev/null 2>&1 || { echo "Docker is not running"; exit 1; }
"${CMD[@]}" 2>&1 | tee "study/logs/$JOB.log"

REWARD=$(python3 - "jobs/$JOB" <<'PY'
import glob, json, sys
for f in glob.glob(f"{sys.argv[1]}/*__*/result.json"):
    r = ((json.load(open(f)).get("verifier_result") or {}).get("rewards") or {}).get("reward")
    print("none" if r is None else r); break
else:
    print("no result")
PY
)
echo "reward    $REWARD"
printf '%s\n' "$(json=; printf '{"ts":"%s","task":"%s","router":"%s","harness":"%s","version":"%s","job":"%s","reward":"%s"}' \
  "$(date -u +%FT%TZ)" "$TASK" "$ROUTER" "$HARNESS" "$VER" "$JOB" "$REWARD")" >> study/live_runs.jsonl
echo "appended to study/live_runs.jsonl"
