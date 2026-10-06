#!/bin/bash
# usage: run_router_wd.sh <task>   (Luna router picks harness, watchdog ACTIVE)
cd /Users/arsh/Desktop/iLab
set -a; . ./.env; set +a; export OPENROUTER_API_KEY
export TB_TASK_DIR=/Users/arsh/.claude/jobs/9d4d6856/tmp/tb2/terminal-bench
router/.venv/bin/python router/router.py --router luna --watchdog active --tag wdact "$1" --execute --cwd . >/dev/null 2>&1
echo "done $1"
