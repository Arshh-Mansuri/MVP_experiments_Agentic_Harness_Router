# AGENTS.md: working on the iLab harness router

Guidance for coding agents. Read this first, then `HOW_IT_WORKS.md` (how a run flows end to end). `README.md` has
setup and commands, `PROJECT_LOG.md` the history and results (newest session at the top), `PROBLEM_DEFINITION.md`
and `STUDY_PLAN.md` the research design.

## What this project is

A study of **harness routing** on Terminal-Bench: for each task, pick which agent harness (terminus-2,
mini-swe-agent, pi) the model works in. The model never changes. Python, standard library where possible, run
from the repo root. Benchmark runs go through the `harbor` CLI and Docker.

## Hard rules (do not break these without the user saying so)

1. **The executor is always GPT-5.6-Luna** (`openrouter/openai/gpt-5.6-luna`). Never change the model a harness
   runs with.
2. **The router is Luna or Jev, nothing else.** Live runs: `study/run_live_router.sh <task> luna|jev`. Jev means
   `~typesafe/jev-latest` through OpenRouter's decisions endpoint (`table_router.decide()`).
   **Never use `typesafe/jev-router`**: it forwards to other models (DeepSeek, GPT-6.1-Sol).
3. **Offline rule.** The router is developed only against saved benchmark results (`jobs/p1-*`, the Qwen
   workbook). Do not run benchmarks to iterate on the router, and never feed live-run results (`jobs/live-*`,
   `study/live_runs.jsonl`) back into the table, prompt or evaluation.
4. **Ask before anything that costs money or time:** Harbor runs, OpenRouter calls (router picks, offline pick
   scripts), Langfuse uploads beyond a run the user asked for. `--dry-run` is always fine, and so is `DRY_RUN=1` on Table A tasks;
 on any other task `DRY_RUN=1` still makes the paid routing call.
5. **Frozen files are frozen.** `router/success_table.json`, `router/harness_profiles.json` and
   `router/table_system_prompt.txt` are checked by hash; code refuses to run if they were hand-edited. Change them
   only by rebuilding (`python3 router/build_success_table.py --include-test`, which also rewrites the prompt), and
   only when the user asks; that changes `table_sha256` for every later decision.
6. **Secrets.** `.env` holds `OPENROUTER_API_KEY`, `OPENCODE_API_KEY` and `LANGFUSE_*`. Never print, log, commit or
   send key values anywhere except their own service; refer to them by name. Do not touch `.claude/` (local
   credentials). The scrubber must not rewrite `.env` or `.claude/`.
7. **Git.** Do not commit unless asked. Never push or force-push to `main` without explicit approval. Do not edit
   or delete past run data in `jobs/`, `jobs_set_aside/` or `study/logs/`; it is the record.

## Where things are

| Path | Contents |
|---|---|
| `router/meta_harness.py`, `router/meta_route.py` | The meta-harness as a Harbor agent (`--agent meta_harness:MetaHarness`, needs `PYTHONPATH=router`); runs in Harbor's Python 3.12, routes in `setup()`, delegates to the chosen harness |
| `router/table_router.py` | The live router: `pick()` (Luna), `decide()` (Jev), `lookup()` (no model, used by offline tools), `Trace` |
| `router/profile_router.py` | Harness list, `task_text()`, profile loading, OpenRouter chat call |
| `router/build_success_table.py` | Builds and freezes the success table + routing prompt |
| `router/router.py`, `router/pick_offline.py` | Older LangGraph pipeline and offline pick replays (Luna/Gemma/classifier comparisons) |
| `study/run_live_router.sh` | One live run: route (or fallback), Harbor, record, Langfuse upload |
| `study/run_final.sh`, `study/final_results.py` | Final 89-task batch with same-harness fallback; its results table |
| `study/langfuse_export.py` | Finished run → one Langfuse trace (needs `~/.venvs/ilab-obs`) |
| `study/run_phase1.sh`, `study/kfold_eval.py`, `study/analyze_phase1.py` | Phase 1 runs and their offline evaluation |
| `study/scrub_secrets.py`, `hooks/pre-commit` | Secret redaction and the commit guard |
| `jobs/` | Harbor output, one folder per job (`p1-*` Phase 1, `live-*` live runs, `direct-*`/`routed-*` older) |
| `study/logs/` | Per-run Harbor log, `<job>.trace.jsonl` timeline, `langfuse_sent.jsonl` ledger |
| `archive/` | Dead code and old data kept for the record; nothing live imports it |

## Environments

- **System `python3` (3.9)** runs the router, the live runner and most study scripts (standard library only).
  Keep that code 3.9-compatible: no `match`, no `X | Y` types, no backslashes inside f-string expressions.
- **`router/.venv`** (langchain, langgraph, pandas, sklearn) is only for `router/router.py` and a few study
  scripts. The repo sits in an iCloud folder that offloads venv files, so imports can hang for minutes; prefer
  system Python where you can.
- **`~/.venvs/ilab-obs`** (Python 3.12, `langfuse==4.17.0`) is only for `study/langfuse_export.py`.
- Load keys with `set -a; . ./.env; set +a` before anything that calls an API.

## Safe commands (no cost, no network)

```bash
python3 router/table_router.py --explain fix-git                  # step-by-step routing decision for a known task
DRY_RUN=1 study/run_live_router.sh fix-git luna                   # route + print the Harbor command (fix-git is in Table A)
study/preflight.sh                                                # machine readiness for study/run_final.sh
~/.venvs/ilab-obs/bin/python study/langfuse_export.py jobs/<job> --dry-run   # trace tree, unit count, secrets found
bash -n study/run_live_router.sh                                   # shell syntax check
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" <file.py>   # syntax check without writing .pyc
```

`DRY_RUN=1` with an invalid router still creates a stub `study/logs/<job>.trace.jsonl`; delete it if you made one.

## Gotchas we have already hit

- **Langfuse v4 does not deduplicate.** Re-sending a span with the same id creates duplicates. The exporter sends
  each job once (ledger `study/logs/langfuse_sent.jsonl`); use `--replace` to delete and re-send. Every
  observation is a billed unit (free plan 50k/month), so keep traces lean: tool calls are grouped per step, logs
  go in metadata.
- **Langfuse reads:** this org cannot use legacy read APIs (`/api/public/traces` returns 410). Use
  `lf.api.observations.get_many(...)` (v2, needs `from_start_time`/`to_start_time` as datetimes; fields are
  snake_case on the returned objects) and `lf.api.scores_v3.get_many_v3(...)`.
- **Langfuse MCP** (`.cursor/mcp.json`, gitignored; 86 tools incl. `queryMetrics` and dashboard widgets) is the
  quickest way to query runs. Dashboards live in `study/langfuse_dashboard.py`; edit `WIDGETS` there and run
  `--check` then `--replace` rather than editing widgets by hand. The MCP endpoint rate-limits bursts (429).
- **Trace-wide attributes** (session, tags, trace name, environment) must be set on every span, not only the root.
- **Harness logs can contain keys**: harnesses inside the container see the OpenRouter key and agents sometimes
  dump `env`. Scrub before committing or uploading (`study/scrub_secrets.py`, the exporter does it already).
- **terminus-2 on fix-git** sometimes gets stuck in git's `less` pager. That is a known harness risk, not a
  pipeline bug; do not "fix" it by changing the table from live results (offline rule).
- **The sandbox** blocks writes outside the workspace (e.g. `py_compile` caches) and most network; retry with the
  needed permission rather than working around it.

## Conventions

- Match the surrounding code: compact, standard library, few comments; a comment states a constraint the code
  cannot show, not what the next line does.
- Routing code returns `(harness, info)`; `info` always has `match`, `reason`, `seconds`, `tokens`, `cost`,
  `underlying_model`, `table_sha256` and a `trace` of steps. Keep that shape; the live runner and the exporter
  depend on it.
- Keep observation and step names stable (`solve-task`, `route-task`, `decide-next-action`, `verify-solution`);
  dashboards and filters key on them.
- After changing behaviour, update `README.md`/`HOW_IT_WORKS.md` if usage changed, and add a short dated note to
  `PROJECT_LOG.md`.
