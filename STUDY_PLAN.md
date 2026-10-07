# Study plan: does choosing the harness per task improve results?

> **Amendment, 7 Oct 2026:** aligned with the team's problem definition in `PROBLEM_DEFINITION.md`. Changes:
> k-fold cross-validation replay is now the main evaluation (the development / test split stays as a secondary
> check); both the cheapest-pass and the stable oracle are reported; rule-based routers (keywords, decision tree,
> k-NN) and a fallback triggered only by run-time signals are added; the hard-coded lookup is a cache, not a router.

Status: **draft, written before any Phase 1 data is collected.** Once Phase 1 starts, the question, metrics,
thresholds and test set below are frozen; any later change must be recorded in `PROJECT_LOG.md` with the reason.

## 1. Question

With the model fixed at **GPT-5.6-Luna**, does choosing the harness per task (`terminus-2`, `mini-swe-agent`, `pi`)
with a router beat always using the best single harness, on tasks the router has never seen?

Only the harness varies. The model, its settings, harness versions and task timeouts stay the same for every run.
Routers stay blind: they see the task text (and, where stated, task metadata), never benchmark outcomes.

## 2. Metrics and success criteria (both are primary)

Measured on the **test set** only, against the best fixed harness chosen on the development set.

| Claim | Criterion |
|---|---|
| Routing improves pass rate | Router pass rate at least **5 percentage points** above the best fixed harness, with the 95% bootstrap confidence interval of the paired difference excluding 0 |
| Routing improves cost | Cost per pass at least **30% lower** than the best fixed harness, with pass rate no more than **3 points** below it |

Pass rate for a task and harness is the mean reward over its repeats. Cost is the mean recorded `cost_usd`.
Routing cost (the router's own LLM calls) is added to the router's cost.

## 3. Phases

### Phase 0: pilot (5 tasks, Jev router) - withdrawn
Withdrawn on 3 Oct. It used Jev only as a drop-in replacement for Luna as the picker, with the hand-written cards,
which is not the intended design. Replaced by the profile-based Jev router in Phase 2.

### Phase 1: measure the headroom
- **Tasks:** size decided after the pilot (default **45**). Drawn from Terminal-Bench 2 by `study/select_tasks.py`
  with a fixed seed.
- **Split:** tasks already run in earlier studies go to the **development set**; the **test set** is drawn only
  from tasks never run before, so nobody has seen their outcomes. Target about 60% development / 40% test.
- **Runs:** every task x every harness x **3 repeats**, via `study/run_phase1.sh`. Infrastructure failures
  (timeouts at setup, missing reward file, API errors) are rerun, not counted as fails.
- **Output:** per task and harness, mean pass rate and mean cost. From these: the **stable oracle** (best harness
  per task using repeat means), each fixed harness, and random choice.
- **Go / no-go:** if the stable oracle on the development set beats the best fixed harness by less than 5 points,
  no router can meet the pass-rate criterion; the study then focuses on the cost criterion.

### Phase 2: build routers (development set only)
Main router: **Luna researches, Jev picks.**
1. Luna reads the source code of each harness once (Harbor's wrappers plus the mini-swe-agent 2.4.6 and pi 0.85.1
   packages that Harbor installs) and writes a profile of each: interaction model, tools, interactive programs,
   long-running processes, file editing, observation, limits, images, strengths, weaknesses, when to choose it.
   No task names, task text or benchmark results are used (`router/harness_research.py`).
2. The profiles are frozen with a content hash (`router/harness_profiles.json`, readable copy `.md`).
3. For each task, Jev gets only the frozen profiles and the task text and picks the harness
   (`router.py --router jev`, offline `router/pick_offline.py`). No hand-written rules and no default harness.

Other candidates:
- Luna picking from the same profiles (`--router luna-profiles`): separates the effect of the profiles from
  the effect of Jev
- Luna router with the hand-written cards and rules (`--router luna`, offline name `luna-cards`)
- keyword rules (from the team meeting)
- TF-IDF gate and embedding nearest-neighbour (scored leave-one-out within the development set)
- cost-aware rule: default to the cheapest harness, override only when the router is confident

All routers are frozen (prompts, rules, model versions recorded) before the test set is scored.

### Phase 3: test (once)
- **Offline:** each router's pick on each test task is scored with the Phase 1 means for that task and harness.
  Every router is compared on identical data.
- **Live confirmation:** the best one or two routers are run for real on the test set (3 repeats) to check that
  the offline estimate holds.
- **Statistics:** paired per-task difference against the best fixed harness, mean and 95% bootstrap confidence
  interval over test tasks.

## 4. Reporting

- Pass rate vs cost chart: the three fixed harnesses, random choice, every router, and the stable oracle.
- Test-set table with confidence intervals for both criteria.
- Breakdown by task category (`task.toml` metadata).
- Either outcome is reported: "routing improves X by Y [CI]" or "harness choice changes per-task outcomes by up to
  Y (oracle gap), but it is not predictable from the task description".

## 5. Controls and operations

- Harbor version pinned (currently 0.21.0); model `openrouter/openai/gpt-5.6-luna`.
- Run order randomised; at most 3 runs in parallel; runs under `caffeinate -i`; Docker running.
- Before Phase 1: raise the OpenRouter key limit (Phase 1 at 45 tasks is about 405 runs, roughly $5–12; the key had
  $2.86 left on 29 Sep), and mark the iLab folder "Keep Downloaded" in iCloud.
- Only runs with the Luna model count (`router/outcomes.py` filters on it).

## 6. Scripts

| Script | Purpose |
|---|---|
| `study/select_tasks.py` | Samples tasks with a fixed seed, makes the development / test split, writes `study/phase1_tasks.json` and the run queue `study/phase1_queue.txt` |
| `study/run_phase1.sh` | Runs the queue on Harbor with Luna, skips runs that already have a result, reruns infrastructure failures under a new job name, stops when OpenRouter credit is low |
| `study/analyze_phase1.py` | Phase 1 table and scores (single harnesses, random, perfect picking, routers) with bootstrap CIs; development go/no-go; test set needs `--unseal` and every unseal is logged |
| `study/export_experiments.py` | Writes all experiment data to `study/ilab_experiments.xlsx` and `study/ilab_phase1_runs.csv`; shows everything, since the test set is unsealed |
| `study/kfold_eval.py` | Main evaluation: k-fold replay, learned routers fitted on the training folds only; `--baseline fixed` for claims, `--baseline fold` for the deployment view |
| `study/qwen_vs_luna.py` | Checks the 45-task lookup against the oracle and tests whether Qwen3-Coder's run predicts Luna's well enough to drive the fallback |
| `study/task_features.py` | Task features from `task.toml` and the instruction; shallow decision tree on best harness and on harness disagreement; writes `study/task_features.csv` |
| `study/fallback_sim.py` | Fallback simulation triggered only by crashes and agent timeouts, with a same-harness-retry control and extra cost/time per recovered pass |
| `study/queue_remaining.py` | Queues the 44 tasks Phase 1 did not cover, for full 89-task coverage (`study/phase2_queue.txt`) |
| `study/run_live_router.sh` | One live Harbor run of a router's choice, harness version pinned; appends to `study/live_runs.jsonl` |
| `router/harness_research.py` | Luna writes the harness profiles from source code |
| `router/profile_router.py` | Picks a harness from the frozen profiles (Jev or Luna) |
| `router/pick_offline.py` | Makes and saves picks for all Phase 1 tasks (`router/picks_profiles.json`); `--analogy-only` makes table-router picks that are routing decisions rather than cache hits |
| `router/outcomes.py` | Task x harness reward table from `jobs/`; prints development tasks only unless `--unseal` (logged) |
