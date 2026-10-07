# Agentic Harness Router (MVP experiments)

Can we improve results on [Terminal-Bench](https://www.tbench.ai/) by sending each task to the agent harness best
suited to it, instead of always using one harness?

For each task a **router** picks one of three harnesses (`terminus-2`, `mini-swe-agent`, `pi`), then the task runs in
that harness on [Harbor](https://github.com/laude-institute/harbor) with **GPT-5.6-Luna** (via OpenRouter) as the
model. The model never changes; only the harness does.

- New here? Start with **[Final run: quick start](#final-run-quick-start)** below.
- How a run flows end to end: [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md).
- Rules for coding agents working on the repo: [`AGENTS.md`](AGENTS.md).
- History, results and open issues: [`PROJECT_LOG.md`](PROJECT_LOG.md). Research design:
  [`PROBLEM_DEFINITION.md`](PROBLEM_DEFINITION.md), [`STUDY_PLAN.md`](STUDY_PLAN.md).

---

## Final run: quick start

The final run sends every task through the live pipeline with **Luna as the router and Luna doing the task**:

1. **Route.** The router picks a harness for the task.
   - For the 45 tasks Luna has already run, the pick comes from the frozen success table, with no model call.
   - For the 44 new tasks, Luna is asked once, with the frozen routing prompt.
2. **Run.** Harbor runs the task in Docker with that harness. The harness version is pinned.
3. **Verify.** The task's own tests score it as a reward of 0 or 1.
4. **Record.** The result goes to `jobs/`, `study/live_runs.jsonl` and `study/logs/`, and is uploaded to Langfuse.

### What you need

| | |
|---|---|
| Machine | macOS or Linux, at least 16 GB RAM, **40 GB or more of free disk** (every task builds its own Docker image) |
| Docker | [Docker Desktop](https://www.docker.com/products/docker-desktop/), running. Give it about 12 GB of memory (Settings, Resources) for 3 tasks at a time; 8 GB with `PARALLEL=1` |
| Python | `python3` 3.9 or newer. On macOS, `xcode-select --install` provides it |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh`. It installs Harbor and the Langfuse venv |
| OpenRouter key | Pays for Luna. Budget about **$3** for all 89 tasks (Phase 1 averaged $0.02 per run) |
| Langfuse keys | Optional. Without them runs still work; they just are not uploaded |
| Time | About **4–5 hours** for all 89 tasks with 3 at a time (median 5 minutes per task, a few take over an hour) |

### 1. Install (once)

```bash
git clone https://github.com/Arshh-Mansuri/MVP_experiments_Agentic_Harness_Router.git
cd MVP_experiments_Agentic_Harness_Router
git config core.hooksPath hooks              # pre-commit hook that blocks commits containing API keys

uv tool install harbor==0.21.0               # the benchmark runner, pinned to the version the study used
harbor download terminal-bench --cache       # task instructions and tests into ~/.cache/harbor/tasks

cp .env.example .env                         # then open .env and fill in the keys (see below)

# optional, for Langfuse uploads (the SDK needs Python 3.10+, so it gets its own venv)
uv venv ~/.venvs/ilab-obs --python 3.12
uv pip install --python ~/.venvs/ilab-obs/bin/python langfuse==4.17.0
```

`.env` (never commit it; it is gitignored):

```bash
OPENROUTER_API_KEY=sk-or-...                    # required
LANGFUSE_PUBLIC_KEY=pk-lf-...                   # optional
LANGFUSE_SECRET_KEY=sk-lf-...                   # optional
LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com
```

If you use your own OpenAI credits through OpenRouter (BYOK, under Settings, Integrations on openrouter.ai):
- turn on "Never use shared capacity", so a failing OpenAI key does not silently fall back to OpenRouter credit;
- after the smoke test below, check that the cost recorded in `study/live_runs.jsonl` is not near zero.

### 2. Check the machine (free)

```bash
study/preflight.sh                                  # tools, Docker, disk, keys, frozen router files, task cache, Langfuse
DRY_RUN=1 study/run_live_router.sh fix-git luna     # shows the routing decision and the Harbor command, runs nothing
                                                    # (free for the 45 table tasks; a new task costs one routing call)
```

Fix every `FAIL` line before going on. `warn` lines are fine.

### 3. Smoke test (about 2 minutes, about $0.01)

```bash
study/run_live_router.sh fix-git luna
```

It should end with `"reward": 1.0` (or 0.0; fix-git sometimes fails on its own) and a Langfuse URL.

### 4. The final run

```bash
study/run_final.sh                                  # all 89 tasks: the 44 new ones first, then the 45 known ones
study/run_final.sh study/final_tasks_unseen.txt     # only the 44 tasks Luna has never run
study/run_final.sh study/final_tasks_seen.txt       # only the 45 tasks already in the success table
```

- **3 tasks at a time.** This is the same as Phase 1, and takes about 4–5 hours for all 89. Use `PARALLEL=1` on a
  weak machine: about 12 hours.
- **Resumable.** If it stops (crash, Ctrl-C, reboot, Docker restart), run the same command again. Tasks that already
  have a score in this batch are skipped.
- **Retries.** A task that ends without a score (Harbor or Docker failed before the tests ran) is retried once
  straight away, and again on the next rerun. A score of 0 is a real result and is never retried.
- **Disk.** Below 20 GB free it removes unused Docker images. Below 6 GB after that, it stops launching tasks.
- **Credit.** It stops launching tasks when the OpenRouter key has less than $0.50 left. `MIN_CREDIT=0` turns this
  off.
- **Stopping cleanly.** `touch study/logs/STOP` lets running tasks finish and starts no new ones. Delete the file
  before running again.
- **Keeps the machine awake** on macOS with `caffeinate`. Keep the laptop plugged in and the lid open.
- **Batch name.** It is `final` by default. A different one starts a fresh batch:
  `study/run_final.sh study/final_tasks_all.txt final2`.

Progress prints one line per task (`start`, `done … reward=1.0`, `fail`, `skip`). Each task's full console output is
in `study/logs/final-console/<task>.out`. At the end it prints the batch summary (scored, passed, total cost) and
lists any task left without a score.

### 5. Where the results are

| Where | What |
|---|---|
| `study/live_runs.jsonl` | One line per run: task, harness, why it was chosen, reward, cost, `batch: final` |
| `jobs/live-final-luna-<task>-<time>/` | Harbor's full output: trajectories, test results |
| `study/logs/<job>.log`, `<job>.trace.jsonl` | Harbor's console log, and the timeline of each stage |
| Langfuse, dashboard "iLab router: live runs" | One trace per run (filter by tag `batch:final`), with pass rate and spend charts |

### 6. Send the results back

The pre-commit hook blocks commits that contain an API key. Agents inside the container can see the key and sometimes
print it, so scrub first, then push to a branch rather than `main`:

```bash
python3 study/scrub_secrets.py --apply             # redacts any key that ended up in a run log
git checkout -b final-run
git add jobs/live-final-* study/live_runs.jsonl study/logs
git commit -m "Final run: Luna router, Luna executor"
git push -u origin final-run
```

If the laptop cannot push to the repo, zip those same paths and send the zip instead.

---

## Key findings so far

Measured on 27 development tasks x 3 harnesses x 3 repeats (453 runs, GPT-5.6-Luna throughout), cross-validated in
[`study/kfold_eval.py`](study/kfold_eval.py). The full statement of the problem and the answers is in
[`PROBLEM_DEFINITION.md`](PROBLEM_DEFINITION.md).

- **Harness choice matters, but no router captures it.**
  - Perfect picking reaches 75.3%, against 61.7% for always `mini-swe-agent`: +13.6 points [+4.9, +23.5].
  - Under 5-fold cross-validation every router lands at or below that baseline:
    - Luna: 58.0%;
    - Jev: 56.8%;
    - k-NN on task text: 51.9–55.6%.
  - The result is stable across seeds 0, 1 and 2.
- **Much of the apparent headroom is luck.**
  - Only 50 of 81 task x harness cells give the same result on all three repeats.
  - The single-run oracle reads 81.5%, which is 6.2 points above the stable oracle.
- **Task metadata carries almost no signal.**
  - A depth-2 tree on `task.toml` fields gets 52% leave-one-out accuracy, against 41% for always `mini-swe-agent`.
- **Fallback helps, but it is crash recovery rather than routing.**
  - Retrying after an observable failure lifts always-`terminus-2` from 51.9% to 61.7%.
  - Retrying the *same* harness accounts for +8.6 points of that.
- **Cost is the clearer lever.**
  - `terminus-2` costs about 2.2x as much as `mini-swe-agent` on the same tasks, without passing more of them.
- **Memorising beats routing on tasks we have already run.**
  - The success table hits the best-of-3 ceiling on the 45 known tasks: 70.4%, against 54.8% for always
    `mini-swe-agent`.
  - That is a cache, not a router. Cross-validated, the same approach reaches only 58.3%.
  - So the 44 new tasks are where the final run actually tests routing.

## Routers

| Router | Where | Sees past results? |
|---|---|---|
| `luna` | live (`study/run_live_router.sh`, `study/run_final.sh`) | Yes: known tasks come from the frozen success table, other tasks go to Luna with the table in its prompt |
| `jev` | live | Same table; new tasks go to Jev (`~typesafe/jev-latest`) through OpenRouter's decisions endpoint |
| `--router luna`, `gemma`, `luna-profiles` | `router/router.py` (older) | No: task text plus harness descriptions only |
| `--router luna-table` | `router/router.py` | Yes, the success table in the prompt; scored only with `pick_offline.py --analogy-only` |
| `--router lookup` | offline tools | Yes, entirely: a table read with no model call, reported as a cache |
| `--router gate` | `router/router.py` | Yes: TF-IDF classifier trained on the Qwen3-Coder results |

`typesafe/jev-router` is not used. It forwards each request to other models (DeepSeek, GPT-6.1-Sol), so its answers
were never Jev's own. Its old picks stay in `router/picks_profiles.json` as a record.

The 45 Phase 1 tasks were once split into development and held-out test tasks. The seal was broken on purpose on 7 Oct
so that the table covers all 45 tasks. Since then, only the 44 Phase 2 tasks measure generalisation. `--unseal` still
logs to `study/test_unseal_log.jsonl`, so the before-and-after numbers can be reproduced.

## Repository layout

| Path | What it is |
|---|---|
| `study/run_final.sh` | The final run: a task list through the live pipeline with Luna, resumable |
| `study/preflight.sh` | Free readiness check for a machine |
| `study/final_tasks_*.txt` | Task lists: `all` (89), `unseen` (44 new), `seen` (45 known) |
| `study/run_live_router.sh` | One live run: route, Harbor, record, Langfuse upload |
| `study/langfuse_export.py`, `study/langfuse_dashboard.py` | Run to Langfuse trace; the Langfuse dashboard definition |
| `router/table_router.py` | The live router: `pick()` (Luna), `decide()` (Jev), `lookup()` (no model, offline only) |
| `router/success_table.json`, `router/table_system_prompt.txt` | Frozen table and routing prompt, checked by hash |
| `router/profile_router.py` | Harness list, task text loading, the OpenRouter call |
| `router/build_success_table.py` | Rebuilds and re-freezes the table and prompt (changes `table_sha256`) |
| `router/router.py`, `router/pick_offline.py` | Older LangGraph pipeline and offline pick replays |
| `study/run_phase1.sh`, `study/kfold_eval.py`, `study/analyze_phase1.py` | Phase 1 runs and their evaluation |
| `study/scrub_secrets.py`, `hooks/pre-commit` | Secret redaction and the commit guard |
| `jobs/` | Harbor output, one folder per job (`p1-*` Phase 1, `live-*` live runs) |
| `study/logs/` | Per-run Harbor log and trace timeline, Langfuse upload ledger |
| `archive/` | Dead code and old data kept for the record |
| `Qwen_89_Task_Comparison_2026-09-20.xlsx` | Qwen3-Coder 480B baseline: 89 tasks x 4 harnesses |

## Research commands

```bash
python3 router/table_router.py --explain fix-git   # why a task goes to its harness (no API call)
python3 study/kfold_eval.py --baseline fixed       # main cross-validated evaluation of saved runs
python3 study/analyze_phase1.py                    # single development/test split
python3 study/export_experiments.py                # writes study/ilab_experiments.xlsx
~/.venvs/ilab-obs/bin/python study/langfuse_export.py jobs/<job> --dry-run   # preview a Langfuse trace
~/.venvs/ilab-obs/bin/python study/langfuse_dashboard.py --check             # test the dashboard queries
```

The older LangGraph pipeline needs its own venv:

```bash
cd router && python3 -m venv .venv
.venv/bin/pip install langchain-openai langchain-ollama langgraph pandas openpyxl scikit-learn
```

## Known issues

- **Keys inside run logs.** The OpenRouter key reaches the harnesses inside the container, and agents sometimes dump
  `env` into transcripts. The hook refuses such commits; `python3 study/scrub_secrets.py --apply` redacts them.
- **The `less` pager trap.** `terminus-2` on fix-git sometimes gets stuck in git's `less` pager and fails. This is a
  known harness risk, not a pipeline bug.
- **iCloud folders.** If the repo lives in an iCloud-synced folder, macOS may offload venv files, and Python can then
  take minutes to start. Keep venvs outside iCloud.
- **Mixed `pi` versions.** Phase 1 runs mix `pi` 1.0.0, 1.0.1 and 1.0.2. Live runs pin terminus-2 2.0.0,
  mini-swe-agent 2.4.6 and pi 1.0.1.
