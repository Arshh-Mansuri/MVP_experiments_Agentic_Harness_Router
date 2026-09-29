# Agentic Harness Router (MVP experiments)

Can we improve results on [Terminal-Bench](https://www.tbench.ai/) by sending each task to the agent harness best
suited to it, instead of always using one harness?

This repo routes each task to one of three harnesses (`terminus-2`, `mini-swe-agent`, `pi`) and runs it on
[Harbor](https://github.com/laude-institute/harbor), with GPT-5.6-Luna (via OpenRouter) as the model inside every
harness. Every router is compared against three baselines: the best fixed harness, random choice, and the oracle
(the best harness per task in hindsight, i.e. perfect routing).

Routers are **blind**: their prompts contain only the task text and facts about how each harness works, never past
benchmark results.

## Key findings so far

- **Routing by task description has not beaten a fixed harness.** On the 21 tasks measured with all three
  harnesses: oracle 15.9/21 (76%), always `mini-swe-agent` 13.0 (62%), routers and random choice about 12.5–13.0.
- **Little headroom, much of it noise.** All harnesses score the same on 13 of 21 tasks, 4 tasks are never solved,
  and the same harness often passes and fails the same task on repeat runs.
- **Cost is the bigger lever.** `terminus-2` costs about 2.2x `mini-swe-agent` over the same tasks without passing
  more of them. The current router therefore defaults to `mini-swe-agent` and only switches when a task clearly
  needs live terminal state (`terminus-2`) or images / heavy file editing (`pi`).
- **Prompt engineering changes picks, not accuracy.** Four prompt designs were tested; none reliably beat the
  fixed baseline (details in `PROJECT_LOG.md`).
- **A supervised classifier found no signal either.** TF-IDF + logistic regression / kNN / random forest on Qwen's
  89-task baseline all collapsed to "always pick mini-swe-agent" under leave-one-out evaluation.

Full details: [`PROJECT_LOG.md`](PROJECT_LOG.md) (findings, errors, fixes, open issues) and
[`GPT-5.6-LUNA-BENCHMARK-RESULTS.md`](GPT-5.6-LUNA-BENCHMARK-RESULTS.md) (per-experiment write-ups; its later
sections supersede the early ones).

## Repository layout

| Path | What it is |
|---|---|
| `router/router.py` | Main router (LangGraph): load task, classify, validate, run on Harbor, log |
| `router/router2.py` | Harness descriptions, decision rules and Luna pick/scoring functions shared by all routers |
| `router/gate_router.py` | TF-IDF + logistic regression router trained on the Qwen 89-task baseline (`--router gate`) |
| `router/cv_gate.py` | Leave-one-out evaluation of classifier routers on the Qwen data |
| `router/eval_routers.py` | Offline evaluation of Luna router variants against measured outcomes |
| `router/prompt_iterations.py` | Compares router prompt designs offline (no Harbor runs) |
| `router/outcomes.py` | Builds the task x harness reward table from `jobs/` |
| `router/archive_watchdog/` | Early-stopping watchdog experiment (dropped) |
| `router/*.jsonl`, `router/*results*.json` | Routing logs and experiment results |
| `jobs/` | Harbor job outputs (configs, trajectories, verifier results) for every run |
| `study/` | Batch-run queues and scripts used for the studies |
| `Qwen_89_Task_Comparison_2026-09-20.xlsx` | Qwen3-Coder 480B baseline: 89 tasks x 4 harnesses |

## Setup

Requirements: Python 3.12, [Harbor](https://github.com/laude-institute/harbor) CLI, Docker Desktop (running), an
OpenRouter API key, and [Ollama](https://ollama.com/) with `gemma3:270m` only if you use the Gemma router.

```bash
cd router
python3 -m venv .venv
.venv/bin/pip install langchain-openai langchain-ollama langgraph pandas openpyxl scikit-learn
```

Create `.env` in the repo root (it is gitignored, never commit it):

```bash
OPENROUTER_API_KEY=sk-or-...
```

Load it before any run:

```bash
set -a; . ./.env; set +a; export OPENROUTER_API_KEY
```

Terminal-Bench tasks are read from Harbor's cache (`~/.cache/harbor/tasks/`); download them with
`harbor download terminal-bench --cache`.

## Usage

Run from the repo root.

```bash
# Route only (no execution): prints the pick for each task
router/.venv/bin/python router/router.py --router luna fix-git count-dataset-tokens

# Route and run on Harbor (results go to jobs/, a log line to router/router_log.jsonl)
caffeinate -i router/.venv/bin/python router/router.py --router luna fix-git --execute --cwd .

# Skip routing and force a harness
router/.venv/bin/python router/router.py --force pi fix-git --execute --cwd .

# Offline evaluations (no Harbor runs)
cd router
python eval_routers.py train        # or: held
python cv_gate.py
python prompt_iterations.py --reps 2
```

Routers: `--router luna` (GPT-5.6-Luna, default choice for experiments), `--router gemma` (local Gemma 270M,
votes over all harness orderings), `--router gate` (TF-IDF classifier, no LLM cost).

## Known issues

- If the project lives in an iCloud-synced folder (e.g. Desktop), macOS may offload venv files and Python can take
  many minutes to start. Mark the folder "Keep Downloaded" or keep the venv outside iCloud.
- `study/run_wd.sh` and `study/run_router_wd.sh` use a `--watchdog` flag that no longer exists.
- `router/picks_cache.json` caches picks from an older prompt; delete it before re-running `eval_routers.py`.

More in [`PROJECT_LOG.md`](PROJECT_LOG.md).

## Next steps

Package the router as a single Harbor agent (meta-harness), test embedding-based routing on unseen tasks, track
cost per pass, and evaluate on fresh tasks with repeated runs.
