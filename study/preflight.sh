#!/usr/bin/env bash
# Checks that this machine is ready for study/run_final.sh. Costs nothing: no model calls, no Harbor runs.
# usage: study/preflight.sh [task-list]     (default study/final_tasks_all.txt)
set -uo pipefail
cd "$(dirname "$0")/.."
LIST="${1:-study/final_tasks_all.txt}"
FAIL=0
ok()   { echo "  ok    $*"; }
warn() { echo "  warn  $*"; }
bad()  { echo "  FAIL  $*"; FAIL=1; }

echo "tools"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' && ok "python3 $(python3 -V 2>&1 | cut -d' ' -f2)" \
  || bad "python3 3.9 or newer is required"
if command -v harbor >/dev/null; then
  HV=$(harbor --version 2>/dev/null)
  [ "$HV" = 0.21.0 ] && ok "harbor $HV" || warn "harbor $HV, but the study used 0.21.0 (uv tool install --force harbor==0.21.0)"
else
  bad "harbor not found (uv tool install harbor==0.21.0; see README)"
fi
command -v docker >/dev/null || bad "docker not installed"
docker info >/dev/null 2>&1 && ok "docker is running" || bad "docker is not running (start Docker Desktop)"
FREE_GB=$(df -Pk . | awk 'NR==2 {print int($4 / 1048576)}')
[ "$FREE_GB" -ge 40 ] && ok "${FREE_GB} GB free disk" \
  || warn "only ${FREE_GB} GB free; task images add up, run 'docker system prune' between batches if it fills"

echo "keys (.env; values are never printed)"
if [ -f .env ]; then
  set -a; . ./.env; set +a
  [ -n "${OPENROUTER_API_KEY:-}" ] && ok "OPENROUTER_API_KEY set" || bad "OPENROUTER_API_KEY missing from .env"
  if [ -n "${LANGFUSE_PUBLIC_KEY:-}" ] && [ -n "${LANGFUSE_SECRET_KEY:-}" ] && [ -n "${LANGFUSE_BASE_URL:-${LANGFUSE_HOST:-}}" ]; then
    ok "LANGFUSE_* set"
  else
    warn "LANGFUSE_* not set: runs work, but nothing is uploaded to Langfuse"
  fi
else
  bad "no .env (copy .env.example to .env and fill it in)"
fi

echo "router"
python3 - "$LIST" <<'PY' || FAIL=1
import sys
sys.path.insert(0, "router")
import table_router, profile_router as pr
fail = 0
try:
    t, digest = table_router.load_table()
    table_router.load_system_prompt(digest)
    print(f"  ok    success table and routing prompt frozen (table_sha256 {digest})")
except Exception as e:
    print(f"  FAIL  {e}"); sys.exit(1)
tasks = [l.split()[0] for l in open(sys.argv[1]) if l.strip() and not l.lstrip().startswith("#")]
known = {r["task"] for r in t["table_a"]}
missing = []
for task in tasks:
    try:
        pr.task_text(task)
    except Exception:
        missing.append(task)
if missing:
    print(f"  FAIL  {len(missing)} of {len(tasks)} task instructions not cached: {' '.join(missing[:6])}"
          f"{' ...' if len(missing) > 6 else ''}\n        run: harbor download terminal-bench --cache"); fail = 1
else:
    print(f"  ok    {len(tasks)} tasks in {sys.argv[1]}: {len(set(tasks) & known)} from the table,"
          f" {len(set(tasks) - known)} need one Luna routing call each")
sys.exit(fail)
PY

echo "langfuse"
OBS_PY="${LANGFUSE_OBS_PYTHON:-$HOME/.venvs/ilab-obs/bin/python}"
if [ ! -x "$OBS_PY" ]; then
  warn "no $OBS_PY: uploads are skipped (see README, 'Langfuse')"
elif [ -n "${LANGFUSE_SECRET_KEY:-}" ]; then
  "$OBS_PY" -c 'from langfuse import get_client; import sys; sys.exit(0 if get_client().auth_check() else 1)' >/dev/null 2>&1 \
    && ok "Langfuse keys accepted" || bad "Langfuse auth check failed (keys, LANGFUSE_BASE_URL or network)"
fi

echo "git"
[ "$(git config core.hooksPath)" = hooks ] && ok "secret-scrubbing pre-commit hook enabled" \
  || warn "pre-commit hook off: git config core.hooksPath hooks"

echo
[ "$FAIL" = 0 ] && echo "ready. dry run one task: DRY_RUN=1 study/run_live_router.sh fix-git luna" \
  || { echo "not ready: fix the FAIL lines above"; exit 1; }
