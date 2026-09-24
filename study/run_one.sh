#!/bin/bash
# usage: run_one.sh <task> <agent|router> <rep>
cd /Users/arsh/Desktop/iLab
set -a; . ./.env; set +a; export OPENROUTER_API_KEY
task=$1; who=$2; rep=$3
if [ "$who" = router ]; then
  router/.venv/bin/python router/router.py --router luna "$task" --execute --tag "rep$rep" --cwd . >/dev/null 2>&1
else
  harbor run -t terminal-bench/$task --model openrouter/openai/gpt-5.6-luna --agent $who --job-name "direct-$who-$task-rep$rep" >/dev/null 2>&1
fi
echo "done $task $who $rep"
