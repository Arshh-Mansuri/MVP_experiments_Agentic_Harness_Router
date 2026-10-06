# Agentic Harness Router (MVP experiments)

Can we improve results on [Terminal-Bench](https://www.tbench.ai/) by sending each task to the agent harness best
suited to it, instead of always using one harness?

This repo routes each task to one of three harnesses (`terminus-2`, `mini-swe-agent`, `pi`) and runs it on
[Harbor](https://github.com/laude-institute/harbor), with GPT-5.6-Luna (via OpenRouter) as the model inside every
harness. **The model never varies; only the harness does.** Every router is compared against the best fixed
harness, random choice, and the oracle (the best harness per task in hindsight, i.e. perfect routing).

Most routers here are **blind** - their prompts hold only the task text and facts about how each harness works -
but two deliberately are not, and the distinction matters when reading results:

| Router | Sees past results? |
|---|---|
| `--router luna`, `--router gemma`, `--router jev`, `--router luna-profiles` | No. Task text plus harness capability descriptions only. |
| `--router jev-table`, `--router luna-table` | Yes. The frozen success table is in the system prompt. Scored as a router only with `pick_offline.py --analogy-only`, which removes the task's own row; otherwise a development task is answered from the table and the result is a cache hit, not a routing decision. |
| `--router lookup` | Yes, entirely. A hard-coded table read with no model call. Reported as a **cache**, never as a router. |
| `--router gate` | Yes. Trained on Qwen3-Coder reward labels for all 89 tasks. |

## Key findings so far

Measured on 27 development tasks x 3 harnesses x 3 repeats (453 runs, GPT-5.6-Luna throughout), cross-validated in
[`study/kfold_eval.py`](study/kfold_eval.py). Full statement of the problem and the answers:
[`PROBLEM_DEFINITION.md`](PROBLEM_DEFINITION.md).

- **Harness choice matters, but no router captures it.** Perfect picking reaches 75.3% against 61.7% for always
  `mini-swe-agent` (+13.6 points [+4.9, +23.5]), yet under 5-fold cross-validation every router lands at or below
  the baseline: Luna 58.0%, Jev 56.8%, k-NN on task text 51.9-55.6%. Stable across seeds 0, 1 and 2.
- **Much of the apparent headroom is luck.** Only 50 of 81 task x harness cells give the same result on all three
  repeats, and the single-run oracle reads 81.5%, i.e. 6.2 points above the stable oracle.
- **Task metadata carries almost no signal.** A depth-2 tree on `task.toml` fields gets 52% leave-one-out accuracy
  against 41% for always answering `mini-swe-agent`. 64 of 81 one-hot columns fire on fewer than 3 of the 27 tasks,
  so most of the feature space cannot split at all. Hand-written keyword rules were dropped for this reason.
- **Fallback helps, but it is crash recovery rather than routing.** Retrying after an observable failure lifts
  always-`terminus-2` from 51.9% to 61.7%; retrying the *same* harness gains +8.6 of that, and beats switching
  outright for `mini-swe-agent` (+2.5 against +1.2).
- **Cost is the clearer lever.** `terminus-2` costs about 2.2x `mini-swe-agent` over the same tasks without passing
  more of them. Current recommendation: always `mini-swe-agent` plus a same-harness retry on crash or timeout.

Earlier write-ups: [`PROJECT_LOG.md`](PROJECT_LOG.md) (findings, errors, fixes, open issues) and
[`GPT-5.6-LUNA-BENCHMARK-RESULTS.md`](GPT-5.6-LUNA-BENCHMARK-RESULTS.md) (September per-experiment notes, now
superseded - its early conclusions are contradicted by the 453-run study).

## The test set is sealed

18 of the 45 tasks are a held-out test set. Scoring or printing their rewards requires `--unseal`, and every such
command appends to [`study/test_unseal_log.jsonl`](study/test_unseal_log.jsonl) so each look is on record. This
applies to `study/analyze_phase1.py`, `study/kfold_eval.py`, `study/fallback_sim.py`, `study/task_features.py`,
`study/export_experiments.py` and `router/outcomes.py`.

## Repository layout

| Path | What it is |
|---|---|
| `router/router.py` | Main router (LangGraph): load task, classify, validate, run on Harbor, log |
| `router/router2.py` | Harness descriptions, decision rules and Luna pick/scoring functions shared by all routers |
| `router/gate_router.py` | TF-IDF + logistic regression router trained on the Qwen 89-task baseline (`--router gate`) |
| `router/cv_gate.py` | Leave-one-out evaluation of classifier routers on the Qwen data |
| `router/profile_router.py` | Picks a harness from the frozen harness profiles (Jev or Luna) |
| `router/table_router.py` | Picks from the frozen success table; also the hard-coded `lookup` cache |
| `router/build_success_table.py` | Builds the frozen `success_table.json` (refuses to include test tasks) |
| `router/pick_offline.py` | Makes and stores router picks without running Harbor |
| `router/prompt_iterations.py` | Compares router prompt designs offline (no Harbor runs) |
| `router/outcomes.py` | Task x harness reward table from `jobs/`; prints development tasks unless `--unseal` |
| `router/archive_watchdog/` | Early-stopping watchdog experiment (dropped) |
| `router/*.jsonl`, `router/*results*.json` | Routing logs and experiment results |
| `jobs/` | Harbor job outputs (configs, trajectories, verifier results) for every run |
| `study/` | Task selection, run queues, and the analysis scripts (see `STUDY_PLAN.md` section 6) |
| `archive/` | Dead and duplicate files kept for the record; nothing live depends on them |
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

Enable the credential hook. `core.hooksPath` is local config, so a fresh clone has to set it once:

```bash
git config core.hooksPath hooks
```

This matters because the key reaches the harnesses that run inside the container (`mini-swe-agent`, `pi`), so a
task that tells the agent to hunt for a password will make it dump `env` into a transcript we commit — which is
how two keys ended up in a public commit (see `PROJECT_LOG.md` section 3f). The hook refuses such a commit;
`python3 study/scrub_secrets.py --apply` redacts artefacts that already contain one.

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

# The study: run the queue, then score it (no Harbor runs needed for scoring)
study/run_phase1.sh                          # harness versions are pinned inside the script
python3 study/kfold_eval.py --baseline fixed # main evaluation, cross-validated
python3 study/analyze_phase1.py              # single development/test split, secondary
python3 study/fallback_sim.py --crashes count
python3 study/task_features.py
python3 study/export_experiments.py          # study/ilab_experiments.xlsx

# One live run of a router's choice
study/run_live_router.sh count-dataset-tokens lookup

# Older offline evaluations
cd router
python cv_gate.py
python prompt_iterations.py --reps 2
```

Routers: `--router jev` (Luna researches the harnesses, Jev picks: OpenRouter's `typesafe/jev-router` chooses
from the frozen harness profiles in `router/harness_profiles.md`, which Luna wrote from the harness source code),
`--router luna-profiles` (Luna picks from the same profiles), `--router luna` (Luna with hand-written harness
descriptions), `--router gemma` (local Gemma 270M, votes over all harness orderings), `--router gate`
(TF-IDF classifier, no LLM cost), `--router jev-table` / `--router luna-table` (same models with the frozen
success table in the prompt), `--router lookup` (hard-coded table read, no model call). The last three see past
results; see the table at the top.

## Known issues

- If the project lives in an iCloud-synced folder (e.g. Desktop), macOS may offload venv files and Python can take
  many minutes to start. Mark the folder "Keep Downloaded" or keep the venv outside iCloud.
- The OpenRouter key has returned 401 since 7 Oct, which blocks every LLM router and all new Harbor runs.
- Phase 1 runs mix `pi` 1.0.0, 1.0.1 and 1.0.2, so "pi" is not a single harness in that data. New runs pin the
  version (`V_PI` in `study/run_phase1.sh`).
- 44 of the 89 tasks have no Luna runs yet; the queue is ready in `study/phase2_queue.txt`.

More in [`PROJECT_LOG.md`](PROJECT_LOG.md).

## Next steps

Fill in the remaining 44 tasks, then test a `mini-swe-agent`-first router that only diverts on strong evidence,
since every router so far loses by over-diverting. Also worth doing: package the router as a single Harbor agent
(meta-harness), and confirm the live path end to end with `study/run_live_router.sh`.
