#!/usr/bin/env bash
# After the current Phase 1 pass ends: run one retry pass for infrastructure failures, write the development-set
# summary, and save everything as a local git commit (no push; the test set stays sealed).
set -uo pipefail
cd "$(dirname "$0")/.."

while pgrep -f "study/run_phase1.sh" >/dev/null; do sleep 60; done
echo "=== first pass finished $(date) ===" >> study/phase1_run.log

echo "=== retry pass $(date) ===" >> study/phase1_run.log
study/run_phase1.sh 2>&1 | grep -v '^skip' >> study/phase1_run.log
echo "=== retry pass finished $(date) ===" >> study/phase1_run.log

{
  echo "Phase 1 development-set summary, generated $(date)"
  echo
  python3 study/analyze_phase1.py
} > study/phase1_dev_summary.txt 2>&1

done_n=$(grep -c '^done' study/phase1_run.log)
git add -A study router jobs PROJECT_LOG.md README.md STUDY_PLAN.md
git commit -q -m "Phase 1 runs ($done_n of 405 slots with results), harness profiles, profile-based Jev router, analysis" \
  -m "Development-set summary in study/phase1_dev_summary.txt. Test set still sealed." \
  && echo "=== committed $(git rev-parse --short HEAD) $(date) ===" >> study/phase1_run.log \
  || echo "=== commit failed $(date) ===" >> study/phase1_run.log
