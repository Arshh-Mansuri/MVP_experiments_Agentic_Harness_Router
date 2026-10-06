#!/bin/bash
# usage: run_wd.sh <task> <harness>   (shadow watchdog, forced harness)
cd /Users/arsh/Desktop/iLab
set -a; . ./.env; set +a; export OPENROUTER_API_KEY
export TB_TASK_DIR=/Users/arsh/.claude/jobs/9d4d6856/tmp/tb2/terminal-bench
router/.venv/bin/python router/router.py --force $2 --watchdog shadow --tag rep1 "$1" --execute --cwd . >/dev/null 2>&1
echo "done $1 $2"
