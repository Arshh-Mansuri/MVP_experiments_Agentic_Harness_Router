#!/usr/bin/env bash
# One live end-to-end run of the router (PROBLEM_DEFINITION.md step 8): choose a harness, then actually run it on
# Harbor with the model fixed to Luna and the harness version pinned. Everything else in the study is an offline
# replay of saved runs, so this is the check that the chosen harness really launches and scores.
#
# usage: study/run_live_router.sh <task> [router]
#   router is 'luna' (default) or 'jev'; the model doing the task is always Luna. Either way a task Luna has
#   already run (Table A in router/success_table.json) is answered from the table with no model call. Any other
#   task goes to the router with the frozen prompt router/table_system_prompt.txt: 'luna' asks GPT-5.6-Luna,
#   'jev' asks Jev itself (~typesafe/jev-latest) through OpenRouter's decisions endpoint.
#   DRY_RUN=1 prints the decision and the Harbor command without running Harbor. Free for Table A tasks; any other
#   task still costs its one routing call.
#   BATCH=<name> groups runs (job name, live_runs.jsonl, Langfuse tag batch:<name>); study/run_final.sh sets it.
#   FALLBACK_HARNESS=<h> FALLBACK_OF=<job> FALLBACK_TRIGGER=<why>: the fallback attempt. No routing call; the harness
#   is the one that failed in <job> (same-harness retry, see study/fallback_sim.py). study/run_final.sh sets these.
#
# Tracing: every stage is printed as it happens and appended to study/logs/<job>.trace.jsonl (one JSON object per
# line: start, route with the router's step-by-step trace, harbor_start, harbor_end, result). Harbor's own output
# goes to study/logs/<job>.log, and the summary line to study/live_runs.jsonl. No secrets are written.
set -euo pipefail
cd "$(dirname "$0")/.."

TASK="${1:?usage: study/run_live_router.sh <task> [router]}"
ROUTER="${2:-luna}"
export MODEL="openrouter/openai/gpt-5.6-luna"
V_TERMINUS2="${V_TERMINUS2:-2.0.0}"; V_MINI="${V_MINI:-2.4.6}"; V_PI="${V_PI:-1.0.1}"
BATCH="${BATCH:-}"
JOB="live-${BATCH:+$BATCH-}$ROUTER-$TASK-$(date +%Y%m%d-%H%M%S)"
while [ -e "jobs/$JOB" ] || [ -e "study/logs/$JOB.trace.jsonl" ]; do
  sleep 1; JOB="live-${BATCH:+$BATCH-}$ROUTER-$TASK-$(date +%Y%m%d-%H%M%S)"
done
TRACE="study/logs/$JOB.trace.jsonl"
mkdir -p study/logs

# ev EVENT [JSON]: append one event to the trace file and print a one-line summary.
ev() {
  python3 - "$1" "${2:-}" "$TRACE" <<'PY'
import datetime, json, sys
event, data, path = sys.argv[1], sys.argv[2], sys.argv[3]
rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "event": event, **(json.loads(data) if data else {})}
open(path, "a").write(json.dumps(rec) + "\n")
brief = {k: v for k, v in rec.items() if k not in ("ts", "event", "trace", "cmd", "raw")}
print(f"[trace {rec['ts'][11:]}] {event}" + (f"  {json.dumps(brief)}" if brief else ""))
PY
}

set -a; . ./.env; set +a; export OPENROUTER_API_KEY
export FALLBACK_HARNESS="${FALLBACK_HARNESS:-}" FALLBACK_OF="${FALLBACK_OF:-}" FALLBACK_TRIGGER="${FALLBACK_TRIGGER:-}"
ev start "$(python3 -c 'import json,sys; d=dict(zip(["task","router","model","job","batch","fallback_of"], sys.argv[1:])); d["batch"]=d["batch"] or None; d["fallback_of"]=d["fallback_of"] or None; print(json.dumps(d))' \
  "$TASK" "$ROUTER" "$MODEL" "$JOB" "$BATCH" "$FALLBACK_OF")"

# Routing: writes the decision (with its step-by-step trace) as one JSON object.
ROUTE=$(TASK="$TASK" ROUTER="$ROUTER" python3 - <<'PY'
import json, os, sys
sys.path.insert(0, "router")
import table_router, profile_router as pr
task, router = os.environ["TASK"], os.environ["ROUTER"]
if os.environ.get("FALLBACK_HARNESS"):
    h, why, of = os.environ["FALLBACK_HARNESS"], os.environ.get("FALLBACK_TRIGGER") or "failure", os.environ["FALLBACK_OF"]
    info = {"match": "fallback", "reason": f"same-harness retry after {why} in {of}",
            "trace": [{"step": "fallback: no routing call", "harness": h, "trigger": why, "first_attempt": of}]}
elif router == "luna":
    h, info = table_router.pick(task, pr.task_text(task), "luna")
elif router == "jev":
    h, info = table_router.decide(task, pr.task_text(task))
else:
    sys.exit(f"unknown router '{router}': use luna or jev")
print(json.dumps({"harness": h, "match": info.get("match"), "reason": info.get("reason"),
                  "route_cost": info.get("cost", 0.0), "route_seconds": info.get("seconds", 0.0),
                  "underlying_model": info.get("underlying_model"), "table_sha256": info.get("table_sha256"),
                  "raw": info.get("raw"), "trace": info.get("trace", [])}, default=str))
PY
)
HARNESS=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["harness"] or "")' "$ROUTE")
case "$HARNESS" in
  terminus-2) VER="$V_TERMINUS2";; mini-swe-agent) VER="$V_MINI";; pi) VER="$V_PI";;
  *) ev route "$ROUTE"; echo "router '$ROUTER' returned '$HARNESS', which is not one of our three harnesses"; exit 1;;
esac
ROUTE=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); d["version"]=sys.argv[2]; print(json.dumps(d))' "$ROUTE" "$VER")
ev route "$ROUTE"
python3 - "$ROUTE" <<'PY'
import json, sys
for i, s in enumerate(json.loads(sys.argv[1])["trace"], 1):
    step = s.pop("step")
    print(f"    {i}. {step}" + (f"  {json.dumps(s)}" if s else ""))
PY

CMD=(harbor run -t "terminal-bench/$TASK" --model "$MODEL" --agent "$HARNESS" --ak "version=$VER" --job-name "$JOB")
if [ "${DRY_RUN:-0}" = 1 ]; then printf 'would run:'; printf ' %q' "${CMD[@]}"; echo; rm -f "$TRACE"; exit 0; fi

docker info >/dev/null 2>&1 || { ev abort '{"why": "Docker is not running"}'; exit 1; }
ev harbor_start "$(python3 -c 'import json,sys; print(json.dumps({"cmd": " ".join(sys.argv[1:])}))' "${CMD[@]}")"
T0=$(date +%s)
set +e
"${CMD[@]}" 2>&1 | tee "study/logs/$JOB.log"
RC=${PIPESTATUS[0]}
set -e
ev harbor_end "{\"exit_code\": $RC, \"seconds\": $(( $(date +%s) - T0 ))}"

# Result: what the agent did and how it ended, from Harbor's result.json and trajectory.
RESULT=$(python3 - "jobs/$JOB" <<'PY'
import datetime, glob, json, sys
def mins(b):
    b = b or {}
    if not (b.get("started_at") and b.get("finished_at")):
        return None
    f = lambda s: datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return round((f(b["finished_at"]) - f(b["started_at"])).total_seconds() / 60, 2)
files = glob.glob(f"{sys.argv[1]}/*__*/result.json")
if not files:
    print(json.dumps({"reward": None, "error": "no result.json"})); sys.exit()
r = json.load(open(files[0])); ar = r.get("agent_result") or {}; exc = r.get("exception_info") or {}
steps = None
for p in glob.glob(f"{files[0].rsplit('/', 1)[0]}/agent/trajectory*.json"):
    try:
        steps = len(json.load(open(p)).get("steps") or [])
    except ValueError:
        pass
print(json.dumps({
    "reward": ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward"),
    "exception": exc.get("exception_type"),
    "exception_message": ((exc.get("exception_message") or "").strip().splitlines() or [None])[0],
    "agent_steps": steps, "input_tokens": ar.get("n_input_tokens"), "cached_tokens": ar.get("n_cache_tokens"),
    "output_tokens": ar.get("n_output_tokens"), "cost_usd": ar.get("cost_usd"),
    "minutes": {"env_setup": mins(r.get("environment_setup")), "agent_setup": mins(r.get("agent_setup")),
                "agent_run": mins(r.get("agent_execution")), "verifier": mins(r.get("verifier")), "total": mins(r)},
    "trial_dir": files[0].rsplit("/", 1)[0]}))
PY
)
ev result "$RESULT"

python3 - "$ROUTE" "$RESULT" "$TASK" "$ROUTER" "$JOB" "$TRACE" "$BATCH" >> study/live_runs.jsonl <<'PY'
import datetime, json, os, sys
route, res = json.loads(sys.argv[1]), json.loads(sys.argv[2])
row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
       "task": sys.argv[3], "router": sys.argv[4], "harness": route["harness"], "version": route["version"],
       "match": route["match"], "reason": route["reason"], "job": sys.argv[5],
       "reward": res.get("reward"), "exception": res.get("exception"), "cost_usd": res.get("cost_usd"),
       "route_cost": route.get("route_cost"), "input_tokens": res.get("input_tokens"),
       "cached_tokens": res.get("cached_tokens"), "output_tokens": res.get("output_tokens"),
       "minutes": (res.get("minutes") or {}).get("total"), "trace": sys.argv[6]}
if sys.argv[7]:
    row["batch"] = sys.argv[7]
if os.environ.get("FALLBACK_OF"):
    row.update(attempt="fallback", fallback_of=os.environ["FALLBACK_OF"], trigger=os.environ.get("FALLBACK_TRIGGER"))
else:
    row["attempt"] = "first"
print(json.dumps(row))
PY
echo "trace     $TRACE"
echo "summary   appended to study/live_runs.jsonl"

# Langfuse: upload this run as one trace (study/langfuse_export.py). Optional and never fails the run.
OBS_PY="${LANGFUSE_OBS_PYTHON:-$HOME/.venvs/ilab-obs/bin/python}"
if [ -x "$OBS_PY" ] && [ -n "${LANGFUSE_PUBLIC_KEY:-}" ] && [ -n "${LANGFUSE_SECRET_KEY:-}" ]; then
  set +e
  URL=$("$OBS_PY" study/langfuse_export.py "jobs/$JOB" 2>>"study/logs/$JOB.log" | tail -1)
  OBS_RC=$?
  set -e
  if [ "$OBS_RC" = 0 ] && [ -n "$URL" ]; then
    ev observability "$(python3 -c 'import json,sys; print(json.dumps({"langfuse": sys.argv[1]}))' "$URL")"
  else
    ev observability '{"langfuse": "upload failed, see the end of the Harbor log"}'
  fi
else
  echo "langfuse  skipped (needs LANGFUSE_* in .env and the ~/.venvs/ilab-obs venv)"
fi
