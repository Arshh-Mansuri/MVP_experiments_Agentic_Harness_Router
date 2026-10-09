# Project log: agentic harness router

Running log of findings, errors, fixes and open issues, to be turned into project documentation later.
Most recent session first. Detailed per-experiment write-ups for 18–22 Sep live in `GPT-5.6-LUNA-BENCHMARK-RESULTS.md`
(note: the top sections of that file are outdated; its later sections supersede them).

Repo: https://github.com/Arshh-Mansuri/MVP_experiments_Agentic_Harness_Router

---

## 1. Project goal

Route each Terminal-Bench task to the agent harness most likely to solve it (`terminus-2`, `mini-swe-agent`, `pi`),
running on Harbor with GPT-5.6-Luna as the executor model, and find out whether routing beats always using one
fixed harness. Every router is compared against three baselines: best fixed harness, random choice, and the
oracle (the best harness per task in hindsight, which is the ceiling for perfect routing).

Routers are kept **blind**: prompts contain only the task text and factual descriptions of how each harness works,
never past benchmark results.

---

## 2. Headline findings (as of 29 Sep 2026)

1. **Routing by task description does not beat a fixed harness.** Across the 21 tasks with outcomes for all
   three harnesses (Luna): oracle 15.9 (76%), always `mini-swe-agent` 13.0 (62%), always `terminus-2` 12.75 (61%),
   routers and random choice about 12.5–13.0 (about 60%).
2. **The headroom is small and partly noise.**
   - On 13 of 21 tasks all three harnesses score the same, so the pick does not matter.
   - 4 tasks were never solved by any harness: `chess-best-move`, `path-tracing`, `torch-pipeline-parallelism`,
     `gcode-to-text`.
   - The same harness often passes and fails the same task across runs (for example `terminus-2` on `fix-git` 2/4,
     on `db-wal-recovery` 1/4; `pi` on `cancel-async-tasks` 2/3). The oracle is partly measuring luck.
   - The best fixed harness flips between splits: `terminus-2` best on the 14 training tasks (77%) and worst on
     the 7 held-out tasks (29%).
3. **Task text seems to carry little signal.** Four classifier families trained on Qwen's 89 tasks all collapsed to
   "always guess the majority harness" (31.5%, oracle 40.4%). Gemma 270M's picks followed list order. Luna rated
   `pi` 4–5 on almost every task.
4. **Cost is the bigger lever.** Over the 21 tasks: `terminus-2` $0.50–0.55, `mini-swe-agent` $0.23, `pi` $0.23,
   oracle $0.21. `terminus-2` costs about 2.2x `mini-swe-agent` without passing more tasks. Per task, the most
   expensive harness costs a median 1.9x the cheapest (max 11.9x).
5. **Prompt wording changes which harness is picked, not whether the right one is found** (see section 3.3).
6. **Repeat promising results before trusting them.** One prompt variant scored 14.67/21 (the best result of any
   router) on its first run, then averaged 11.9 over 8 runs.

---

## 3j. 9 Oct 2026: the meta-harness is a Harbor agent

The brief asks for the router to be built as a meta-harness that Harbor runs as an agent. Until now the routing
happened in bash before Harbor was called with a plain harness name.
- `router/meta_harness.py:MetaHarness` is a Harbor custom agent (`BaseAgent`), loaded with
  `PYTHONPATH=router harbor run ... --agent meta_harness:MetaHarness --ak router=luna|jev`.
- In `setup()` it routes with `router/meta_route.py`, which wraps the same `table_router.pick()`/`decide()`, so
  decisions are unchanged. It writes the decision to `agent/route.json`, builds the chosen harness at its pinned
  version with Harbor's `AgentFactory`, and delegates setup, run and the token and cost accounting to it.
- A fallback passes `--ak force_harness=<h>` (plus `trigger`, `first_job`) and skips routing. It stays a second
  trial run by `study/run_final.sh`: Harbor's agent timeout cancels the whole agent, so a timed-out attempt cannot
  hand over from inside.
- `study/run_live_router.sh` reads `route.json` after Harbor and logs it as the `route` event. The
  `live_runs.jsonl` rows, the Langfuse exporter and `study/final_results.py` are unchanged. `DRY_RUN=1` routes
  outside Harbor and prints the meta-agent command.
- Checked for free: Harbor's factory loads the agent from the import path, and with the inner setup stubbed it
  routes fix-git to terminus-2, build-pov-ray to mini-swe-agent, and a forced fallback to pi.
- Live smoke run `live-luna-fix-git-20261009-202741`: the meta-harness routed fix-git to terminus-2 from the
  table, reward 1.0, 2.1 min, $0.0098, uploaded to Langfuse. `result.json` shows the agent as
  `meta-harness terminus-2@2.0.0`. An earlier attempt (`…-202543`) was interrupted from outside after it had routed.

## 3i. 9 Oct 2026: final run aligned with the Project 16 brief

We checked the brief (iLab S2 2026 project list, Project #16) against the pipeline. Two gaps were closed, and the
baseline question was settled.

**Fallback.** The brief asks for "a fallback harness if the first attempt fails"; the live pipeline had none.
- `study/run_final.sh` now gives each task one fallback attempt when the first attempt fails in a way visible at
  run time. The triggers are those of `study/fallback_sim.py`: no reward, a crash exception, or `AgentTimeoutError`.
- The fallback reruns the same harness, with no routing call. Offline, retrying the same harness recovered as much
  as switching.
- The task's result is the fallback's. The fallback never uses the hidden test result.
- This replaces the generic retry of runs with no reward, which keeps it to the brief's "one fallback retry".
- `study/run_live_router.sh` takes `FALLBACK_HARNESS`/`FALLBACK_OF`/`FALLBACK_TRIGGER`.
- Rows now carry `attempt`, `fallback_of`, `trigger`, tokens and minutes.
- Fallback traces get the Langfuse tag `attempt:fallback`.

**Results table.** `study/final_results.py` is new. It builds the brief's "router vs each single harness"
table from the batch, with no runs and no calls.

**Baseline (team decision).**
- The Qwen3-Coder workbook (89 tasks x 4 harnesses) is the Stage 1 baseline deliverable.
- The like-for-like comparison, with the model held constant, uses Luna's Phase 1 runs on the 45 Table A tasks.
  There, single harnesses are scored with crashes counted as fails, with and without the same-harness fallback.
- The 44 unseen tasks report the router's own score, cost and tokens. Qwen's per-harness results appear beside them
  only as a reference, because Qwen is a different model.
- Running Luna on the 44 missing tasks (132 runs) was considered and not done.

## 3h. 7 Oct 2026 (evening): ready for the final run

The final run uses Luna as both the router and the executor, over all 89 tasks. The 45 known tasks come from the
table; the 44 new ones each get one Luna routing call. It will run on another laptop, so the setup is now
self-contained:
- `study/run_final.sh [list] [batch]` runs a task list through `study/run_live_router.sh <task> luna`. It is
  resumable: tasks already scored in the batch are skipped, and tasks with no reward are retried. It prints a batch
  summary at the end.
- `study/preflight.sh` is a free readiness check: tools, Docker, disk, `.env` names, frozen hashes, task cache,
  Langfuse auth, the pre-commit hook.
- Task lists: `study/final_tasks_{all,unseen,seen}.txt` (89, 44, 45).
- `.env.example` is a template for the keys.
- The live runner takes `BATCH=<name>`. The name goes into the job name (`live-final-luna-…`), into the
  `study/live_runs.jsonl` row (with `route_cost` now included) and into the Langfuse tag `batch:<name>`.
- README rewritten around a fresh-machine quick start.

Estimate from Phase 1: 8.4 minutes and $0.02 per run on average, so $2–3 for 89 tasks, and about 4–5 hours with
3 at a time (12 hours one at a time).

After a full review, the batch runner gained the safeguards `run_phase1.sh` already had:
- `PARALLEL=3`;
- one automatic retry for runs that end without a reward;
- Docker pruning below 20 GB free, and a stop below 6 GB;
- a stop when OpenRouter credit falls under $0.50;
- a `study/logs/STOP` file that stops new launches.

Other fixes:
- The Langfuse exporter crashed on runs that stop before some stage has timestamps (49 of 450 Phase 1 runs).
  Missing stage times now fall back to the last known time, and all 450 build.
- Job names can no longer collide.
- A damaged trajectory file no longer loses a scored result.
- Harbor is pinned to 0.21.0 in the README, and `study/preflight.sh` warns on any other version.
- The pre-commit hook now scans the staged content rather than the working copy.
- `scrub_secrets.py` skips `*_URL`/`*_HOST` values in `.env`, which are not secrets.

A secret scan of every commit on GitHub found no OpenRouter or Langfuse key. The `hf_…` matches are substrings of
encrypted reasoning blobs, and the private keys are throwaway certificates from the openssl task.

## 3g. Session log: 7 Oct 2026 — test set unsealed, lookup covers all 45 tasks

Goal: get the deployment path to the best-of-3-harnesses number on the tasks we have run, then see what can be
built on top. The decision taken first, deliberately and on the record: unseal the 18 test tasks and hard-code
all 45. The seal bought a generalisation measurement; a lookup that covers only 27 of 45 tasks buys nothing.
**All 45 Luna tasks are lookup training data now. The remaining 44 Phase 2 tasks are the held-out set.**

### The table
`build_success_table.py` gained `--include-test`, which logs to `study/test_unseal_log.jsonl` like every other
unsealing. Table A went from 27 rows to 45 (`sha256 c7f5166b6d395def`) with a `split` field per row. The builder
also stopped duplicating the pick logic: it now calls `analyze_phase1.stable_pick`, so the table and the oracle it
is measured against cannot drift apart. That refactor changed **0 of the 27 development picks**, so earlier numbers
still stand. One silent bug fixed on the way: `QWEN_XLSX` still pointed at the repository root after the workbook
was moved to `archive/` in the 3e cleanup, so the builder had been unable to build Table B at all.

### The lookup reaches the ceiling, and that is not a routing result
| Scope | Stable oracle | Lookup, 45 hard-coded | Lookup, development only | Always mini-swe-agent |
|---|---|---|---|---|
| all 45 tasks | 70.4% | **70.4%** | 63.7% | 54.8% |
| the 18 formerly sealed tasks | 63.0% | **63.0%** | 46.3% | 44.4% |

Equal to the oracle by construction, and `study/qwen_vs_luna.py` asserts it rather than assuming it. Unsealing is
worth +6.7 points over the development-only lookup across 45 tasks [+1.5, +13.3] and +16.7 on the 18 [+5.6, +31.5].
Cost per pass is the lowest of any strategy at $0.0254.

This is memorisation. Scored honestly by k-fold over the same 45 tasks (`--tasks all --unseal --baseline fixed`,
44 scored, `qemu-startup` excluded because only terminus-2 ever ran it) the lookup reaches 58.3% (+2.3 [−2.3,
+7.6]) against 56.1% for the baseline, while perfect picking reaches 72.0% (+15.9 [+8.3, +24.2]). Every learned and
LLM router is still at or below the baseline. The headroom is real, larger than on the development set alone, and
nothing generalising has captured any of it.

### Qwen predicts Luna, but cannot carry the fallback
Qwen3-Coder's 89-task run is a different model, so using it is not leakage. It does carry signal:

| Harness | Luna pass rate where Qwen passed | where Qwen failed |
|---|---|---|
| terminus-2 | 69.4% (n=12) | 47.9% (n=32) |
| mini-swe-agent | 83.3% (n=16) | 42.0% (n=27) |
| pi | 86.7% (n=10) | 40.4% (n=33) |

Pooled, Luna passes 36.3 points more often with a harness Qwen passed with, and when Qwen passes at all its harness
is Luna's best one 16/21 times (76% against 33% by chance). But Qwen passed with none of our harnesses on 24 of 45
tasks, so the rule can rarely act: it changes 5 of 45 picks for +2.2 points [−2.2, +7.4]. Below the +5-point
criterion and the CI includes zero, so `lookup()` step 2 was first set to the plain default harness. **Revised the
same day by decision:** the evidence leans positive (76% best-harness hit, cheaper per pass) and the rule only
touches 2 of the 44 unrun tasks (`compile-compcert` -> pi, `vulnerable-secret` -> terminus-2), so `lookup()` now
uses it by default (`use_qwen=False` turns it off). It is on as a judgement call, not a proven gain. All three
candidate rules scored identically, which is not a bug: with a mini-swe-agent-first default and ranking, "first in
a fixed order", "divert only if the default failed" and "best-ranked passer" are the same function.

`lookup()` also skips, for unrun tasks, any harness that failed to install in that task's container in the Qwen
run ("Setup exit 100", read from `router/difficulty_table.json`). The signal transfers: on `qemu-startup` the same
two harnesses then crashed on all 9 of Luna's attempts. It moves `qemu-alpine-ssh` from mini-swe-agent to
terminus-2 and touches nothing else.

### Table router system prompt rewritten
`router/table_system_prompt.txt` (used by `--router jev-table` / `luna-table` for tasks outside Table A) was rewritten
in `table_router.build_system_prompt`. The old prompt listed only each known task's winner and score, so a 3-way tie
such as `fix-git -> terminus-2 (3/3)` read like a terminus-2 speciality, and it told the model to copy the harness of
any similar task. Of the 45 known tasks only 2 have a clear winner (by 2+ runs), 18 lean by one run, 19 are ties and
6 are unsolved. The new prompt shows all three scores per task grouped by that strength, states measured pass rates
and costs, and gives ordered rules that match `lookup()`: skip harnesses that cannot install, follow a Qwen pass
that excludes mini-swe-agent, follow similar tasks only when the evidence is CLEAR (or two LEAN tasks agree) and the
similarity is in what separates harnesses rather than topic, else mini-swe-agent. Same JSON reply format.
**Not yet evaluated:** earlier scores for the table routers were measured with the old prompt; rerun
`pick_offline.py --analogy-only` for jev-table and luna-table (needs the API key) before quoting any.

### Tracing the routing decision
Every routing call now records its steps. `lookup()` and `pick()` return `info["trace"]`, a list of steps (which rule
fired, the Table A scores with cost and tie-break, the setup check, Qwen's results, the decision; for the LLM router
also the prompt sha, model reply, tokens and cost). `ROUTER_LOG=info` (or `debug`, which adds the full prompt and raw
reply) prints those steps to stderr as they happen; API retries log as warnings either way when enabled.
`python3 router/table_router.py --explain TASK` prints the lookup decision with no API call.
`study/run_live_router.sh` writes a timeline per run to `study/logs/<job>.trace.jsonl` (start, route with the trace,
harbor_start, harbor_end with exit code and seconds, result with reward, exception, agent steps, tokens, cost and
minutes per stage) and writes `live_runs.jsonl` with proper JSON escaping. Its `jev-table`/`luna-table` branch was
broken (it passed a task argument `pick_offline.py` does not accept); it now calls `table_router.pick` directly.
No secrets are logged.

### Jev itself as a router (`jev-decide`)
`typesafe/jev-router` forwards each request to another model (DeepSeek V4.1 Flash on 7 Oct, GPT-6.1-Sol in the
offline evaluation), so "Jev" answers were never Jev's. Jev itself, `~typesafe/jev-latest`, cannot use chat
completions; it answers structured questions on `/api/alpha/decisions` (`state` + a `choice` question with
`criteria`) and returns a probability per option. `table_router.decide()` gives it the frozen system prompt plus
the task as `state`; `run_live_router.sh <task> jev-decide` uses it. First live run, nginx-request-logging (not in
Table A): Jev chose mini-swe-agent at 0.92 (terminus-2 0.06, pi 0.02), answered by `typesafe/jev-1.13-20260917`
in 0.6 s for $0.0002, about 8x cheaper than the jev-router call; Luna then passed (reward 1, $0.0030). One run,
not an evaluation.

`typesafe/jev-router` is now removed from every code path (`profile_router.ROUTER_MODELS`, the `jev` and
`jev-table` options in `router.py`, `pick_offline.py` and `run_live_router.sh`; `pick()` defaults to Luna). Its
past picks and the one live `jev-table` run stay on disk as records. Jev is only called as itself, via `jev-decide`.

Live runs now have exactly two routers, `study/run_live_router.sh <task> luna|jev` (default `luna`); the executor is
always Luna. Both answer a Table A task from the table with no model call; any other task goes to the router model
with the frozen prompt (`luna` = `table_router.pick`, `jev` = `table_router.decide`, formerly `luna-table` and
`jev-decide`). The standalone `lookup` option is gone: its Table A step is in both, and its Qwen-based fallback for
unknown tasks is replaced by the router model's decision. Earlier jobs keep their old names (`live-lookup-*`,
`live-jev-decide-*`).

### Langfuse traces of live runs
`study/langfuse_export.py` turns a finished live run into one Langfuse trace, built only from files the run left
behind, so it changes nothing about the run. `run_live_router.sh` calls it at the end and records the link as an
`observability` event; a failed upload never fails the run. Scope is live runs only: the benchmark data stays in
`jobs/` and the workbook, and nothing in Langfuse feeds back into the table (offline rule).

Layout, with names kept stable for dashboards: `solve-task` (input: task instruction; output: harness, reward,
tests, cost) contains `route-task` (the lookup, or the router call with prompt, reply, model, tokens and cost; Jev's
option probabilities included), `set-up-environment`, the harness as an agent (`install-harness`, then one
`decide-next-action` generation per Luna call with thinking, tokens split into cached/reasoning, and cost, and its
tool calls as siblings, grouped into one observation per tool name per model call because every observation is
a billed unit: terminus-2 made 32 command batches in 11 steps on one fix-git run, so grouping took that trace from
52 units to 32; typical runs are 17–23 units, about 2,000 runs a month on the free plan), and `verify-solution` with per-test results (WARNING when reward < 1). Scores: `reward`,
`tests_passed`. Session = task name, so repeats of one task line up; tags `router:`, `harness:`, `match:`;
environment `live`. Spans go over OpenTelemetry (`/api/public/otel/v1/traces`, ingestion version 4), the only path
that keeps the original timestamps. Text is clipped at 20,000 characters and run through `scrub_secrets` first.
Run logs ride along as metadata (no extra units), last 8,000 characters with colour codes stripped: `log_harbor`
(Harbor's job.log and trial.log) and `log_exception` on `solve-task`, `log_console` (terminus-2 pane or mini-swe-agent
output) on the harness, `log_pytest` on `verify-solution`.

Checked by reading the traces back (Observations API v2, Scores API v3): the six live runs give 120 observations
and 12 scores. Luna cost sums to $0.022122, the same as Harbor's, and prompt tokens match per run. All child
observations carry session, tags and trace name. Things learned:
- Langfuse v4 does not deduplicate a span sent twice; re-sending nginx produced 28 observations instead of 14.
  The exporter now sends each job once (ledger `study/logs/langfuse_sent.jsonl`); `--replace` deletes the old trace
  and sends under new ids.
- Trace-wide attributes must be on every span, not only the root, or child observations cannot be filtered.
- This org (created after 16 Sep 2026) cannot use the legacy read APIs (`/api/public/traces`); reads go through
  `/api/public/v2/observations` and `/api/public/v3/scores`.
- Timing inside the agent comes from step timestamps, so a generation spans from the previous step to its own, and
  its tool calls sit at its end. pi's session log was parsed on a saved Phase 1 run (7 generations, 11 tool calls,
  cost matches) but no pi live run exists yet.

### Langfuse MCP and dashboard
Cursor is connected to Langfuse's MCP server (`.cursor/mcp.json`, gitignored). `study/langfuse_dashboard.py`
creates the dashboard "iLab router: live runs" through the same server: 15 widgets covering runs, pass rate,
spend (total, routing, by model, by task, per day), pass rate and Luna calls per configuration, runs and failures
by task, stage durations, failed commands by tool and Luna's token mix. Every query was checked first
(`--check`); on 7 runs it shows a 71% pass rate (fix-git 3 of 5), $0.032 total spend of which $0.0017 routing.

### Difficulty gauge from the Qwen workbook
`router/difficulty.py` rates all 89 tasks easy / medium / hard / very hard from Qwen's results (no fitting). Luna's
pass rate falls with every tier: 94%, 58%, 42%, 36% over the 44 scored tasks. Crashed Qwen trials are not counted
as evidence. It also gives an expected Luna cost per run from Qwen's token use (Spearman 0.74 with Luna's cost,
28% off on a split-half check). It reports difficulty only; it does not choose the harness.

### An unstable baseline nearly produced a false positive
Scored leave-one-task-out, the same Qwen rule looked like **+10.4 points [+4.4, +17.0]** — a clean win. It was an
artefact. Over 45 tasks the three harnesses are nearly tied (terminus-2 54.1%, mini-swe-agent 54.8%, pi 51.1%), so
the leave-one-out "best single harness" flips between mini-swe-agent (31 tasks) and terminus-2 (14), and it flips
*against* the withheld task: dropping a task mini-swe-agent solved is exactly what lets terminus-2 win the average.
The reference therefore scores 42.2%, worse than any fixed harness, and flatters everything compared against it.
`kfold_eval.py` already warned about this for `--baseline fold`; the new script now reports both and makes claims
only on `fixed`. Worth remembering as a general hazard: when candidates are within noise of each other, a baseline
refitted per fold is anti-correlated with the held-out item.

### Also
- `export_experiments.py` dropped `--unseal` (nothing left to seal), gained a **Qwen vs Luna** sheet, and the
  K-fold sheet gained a `task_pool` column so the 27-task and 45-task evaluations sit side by side.
- `README.md`, `STUDY_PLAN.md` and `PROBLEM_DEFINITION.md` now state that the 45 tasks are training data.

---

## 3f. Session log: 7 Oct 2026 — OpenRouter key leaked through a run artefact

### What happened
Two OpenRouter keys were committed in `ce466e2` and pushed to a **public** GitHub repository, in five run
artefacts: 12 occurrences across `jobs/p1-mini-swe-agent-crack-7z-hash-r1-retry1/` (3 files) and
`jobs/p1-pi-crack-7z-hash-r2/` (2 files). One of the two was the key still live in `.env`, which is the likely
explanation for the 401 responses since 7 Oct: OpenRouter disables keys that GitHub's secret scanning reports.

### Root cause
Not a mistake in our code. `crack-7z-hash` instructs the agent to recover a password, so the agent ran `env`
inside the container; the dump included `OPENROUTER_API_KEY` and went straight into the transcript we commit.

The leak is specific to the harnesses that run **inside** the container. `mini-swe-agent` and `pi` live in
`harbor/agents/installed/`, so Harbor passes the key into their environment. `terminus-2` drives the container
from the host and never sees it — it ran all three repeats of the same task and leaked nothing. Any
container-installed harness on any task can do this; `crack-7z-hash` only made it likely.

### Fixes
- `study/scrub_secrets.py` redacts credentials in run artefacts, matching both the literal values in `.env` and
  known credential formats. Byte-level, so it survives the NUL bytes in `mini-swe-agent.txt`. Dry run by
  default; exit status 1 when anything is found, so a hook can call it.
- `hooks/pre-commit` (with `core.hooksPath=hooks`, so it is tracked rather than living in `.git/`) blocks any
  commit whose staged files carry a credential.
- All 12 occurrences redacted to `<REDACTED:OPENROUTER_API_KEY>`. The artefacts stay usable: the ATIF
  trajectory still parses with its 105 steps, and the pi session file with its 69 JSON lines.

### The key is stored in two places
A repo-wide scan found the same OpenRouter key, plus an `OPENCODE_API_KEY`, in
`.claude/settings.local.json`. That file is gitignored and never leaked, but rotation has to update it as well
as `.env` or the tools reading it will hold a dead key. The scrubber skips `.env` and `.claude/` for this
reason: they are the legitimate homes for a credential, and rewriting them would break a working setup without
removing anything from the repository.

### Deliberately not treated as secrets
A naive scan flags 23 more files, because agent logs are full of long random identifiers that happen to contain
`hf_` or `ghp_` mid-string. The scrubber requires a non-token character on each side of a match, and restricts
`hf_`/`ghp_` to their real lengths, so those are left alone. Only the OpenRouter keys actually leaked.

### Still outstanding
Rotating both keys is the only real remediation — redaction does not retract a public push. History rewriting
is a separate decision, since it means a force-push to a protected public branch.

---

## 3e. Session log: 7 Oct 2026 — codebase skim: bugs, leak guards, archive

A read-through of the repository looking for problems rather than new results.

### Bugs fixed
- **An oracle could pick a harness that never ran.** `cell()` reports an empty task x harness cell as pass 0 at
  cost $0, and both oracles tie-break toward the cheaper harness, so a harness with zero runs won. Confirmed on
  `qemu-startup`, where `mini-swe-agent` and `pi` never install: both oracles returned `mini-swe-agent` at $0
  while `terminus-2` was the only harness that actually ran. `stable_pick` and `cheapest_pass_pick` now draw from
  harnesses that produced runs, so both return `terminus-2`. No development number moves (all 27 development tasks
  have all three harnesses); this affected `--count-install-failures` and any test-split scoring.
- **Honest table-router picks were unreachable from the command line.** `table_router.pick` supports
  `exact=False, drop=...` for analogy-only evaluation, but `pick_offline.py` always used the defaults, so every
  saved `jev-table` / `luna-table` development pick was a cache hit that would have been scored as routing. Added
  `pick_offline.py --analogy-only`, stored under `<router>-analogy` so the two kinds can never be averaged
  together. `pick` now raises on `drop` with `exact=True` instead of silently downgrading.
- **`pick_offline.py` demanded an API key for `lookup`**, which makes no request. The key is now read lazily and
  only required by routers that call out; `--routers lookup` runs with no key at all.
- **`fallback_sim.py` silently dropped the cache row** when `study/kfold_results_dev_fixed.json` was absent. It now
  says so and names the command to run first.

### Test-set leak guard
`router/outcomes.py` printed per-task pass rates for everything in `jobs/`, test tasks included, with no guard and
no log entry — the same shape of mistake that exposed the test set on 5 Oct. Its command line now shows
development tasks only; `--split test` or `--split all` needs `--unseal` and appends to
`study/test_unseal_log.jsonl`. `build()` is unchanged, so importers are unaffected.

### Fold purity
`study/kfold_eval.py` built the one-hot matrix over all tasks before splitting, so the category and tag vocabulary
was informed by the held-out fold. `task_features.py` gained `one_hot_vocab()` / `one_hot_apply()` and the tree now
fits the vocabulary on the training fold only. The numbers are identical across seeds 0, 1 and 2, so the leak was
harmless — but the method no longer has to be explained away.

### A sharper reason the metadata tree fails
`task_features.py` now reports inert feature columns, and the result is stark: of 81 binary columns on the 27
development tasks, **2 never fire and 64 fire on fewer than 3 tasks**, so only 17 can split at all at
`min_samples_leaf=3`. Nearly every `category=` and `tag=` column is a singleton. The tree's 52% leave-one-out
accuracy is therefore less "metadata carries no signal" and more "there are not enough tasks per category to learn
one", which is an argument for filling in the remaining 44 tasks.

### Archived (nothing deleted)
`archive/` with a README explaining each file: the two watchdog runners (they pass `--watchdog`, which `router.py`
rejects, and point `TB_TASK_DIR` at a temp path that no longer exists), both copies of `finish_phase1.sh` (a spent
one-shot ending in `git add -A` and an automatic commit), `eval_routers.py` and `picks_cache.json` (September task
lists, old-prompt picks, two `if False` branches in one expression), `router_log 2.jsonl` and the duplicate Qwen
xlsx, and six tracked scratch outputs. `router/prompt_iterations.py` imported `TRAIN`/`HELD` from
`eval_routers.py`, so those two lists were inlined there, verified identical to the originals.

### Docs corrected
- `README.md` claimed "Routers are **blind**: their prompts contain only the task text and facts about how each
  harness works, never past benchmark results." That is false for `table_router.py` (frozen development results in
  the system prompt), `lookup` (a pure table read) and `gate_router.py` (trained on Qwen reward labels). Replaced
  with a per-router table of what each one sees. The findings section, still the 21-task September study, was
  replaced with the Phase 1 and k-fold results, and a section on the sealed test set was added.
- `GPT-5.6-LUNA-BENCHMARK-RESULTS.md` now opens with a superseded notice naming the three claims the 453-run study
  contradicts, the loudest being "Pi harness is the clear winner — perfect success rate", from 3 tasks at 1 run
  each, against pi being the weakest harness at 54.3%.

---

## 3d. Session log: 7 Oct 2026 — cross-validated evaluation, feature analysis, fallback

Implemented the review plan in `PROBLEM_DEFINITION.md`. Headline: **no router beats always `mini-swe-agent`**, and
that now holds under cross-validation rather than on one split.

### k-fold evaluation (`study/kfold_eval.py`) — this is now the main evaluation
- 5 folds over the 27 development tasks. Anything learned from outcomes (k-NN, metadata tree, the lookup table) is
  fitted on the training folds only and predicts the held-out fold, so in-sample leakage cannot inflate it. Fixed
  LLM routers do not learn, so k-fold only changes what they are compared against.
- Two baselines, because the choice matters. `--baseline fold` re-picks the best single harness per training fold:
  it picks terminus-2 on some folds and mini-swe-agent on others and lands at **59.3%**, below always
  mini-swe-agent's 61.7%. That instability makes everything look better than it is, so claims use `--baseline
  fixed` (mini-swe-agent held constant).
- Against the fixed baseline, stable across seeds 0/1/2: lookup cache 64.2% (+2.5 [−2.5, +8.6], cost per pass
  −15%), metadata tree 58.0–61.7%, Luna profiles 58.0%, Jev 56.8%, k-NN on task text 51.9–55.6% (CI excludes zero
  on two of three seeds, i.e. reliably **worse**). Nothing meets the +5-point criterion.
- The lookup cache's +2.5 is entirely the Qwen fallback and is seed-independent, because a held-out task is never
  in the training table.

### Feature analysis (`study/task_features.py`)
- Features from `task.toml` (difficulty, category, tags, expert/junior minutes, agent timeout, memory) plus
  instruction length and keyword flags, for all 45 tasks -> `study/task_features.csv`.
- Depth-2 tree for best harness: **52% leave-one-out accuracy against 41%** for always answering mini-swe-agent.
  Predicting *whether* the harnesses disagree is worse than guessing: 48% against a 70% majority. Splits are on
  `instruction_chars` and `junior_min`, which is length, not content.
- On that evidence the hand-written keyword/regex router was dropped (user's call, 7 Oct): with no usable keyword
  split, writing rules by hand would be fitting 27 tasks by eye. k-NN and the metadata tree stand in as the
  learned routers.

### Fallback simulation (`study/fallback_sim.py`)
- Triggers use only what is visible while a run happens: the harness crashed with no result (49 Phase 1 runs) or
  the agent hit its time limit (`AgentTimeoutError`, 18 runs, 17 of which then failed the tests). The verifier's
  reward is never used to trigger.
- `--crashes count` uses the first attempt of each repeat, so a crash reaches the fallback as a deployment would
  see it; `--crashes superseded` uses the manual same-harness retry we actually ran and matches
  `analyze_phase1.py`. The two differ a lot: always-terminus-2 reads 51.9% in the first mode, 60.5% in the second.
- One retry on the cheapest untried harness: terminus-2 51.9% -> 61.7%, pi 49.4% -> 54.3%, mini-swe-agent
  59.3% -> 60.5%, at roughly $0.02–$0.06 and 0.1–0.5 h per extra pass. A second retry adds nothing.
- **Same-harness retry control:** +8.6 (terminus-2), +4.9 (pi), **+2.5 for mini-swe-agent against +1.2 for
  switching**, +3.7 for the lookup cache against +1.2. So the fallback's gain is crash recovery, not harness
  choice, and for the harness we would actually ship, plain retry is better. Reported this way from now on.

### Harness version drift (a confound we had not caught)
- Phase 1 runs mix **pi 1.0.0 (7 runs), 1.0.1 (87), 1.0.2 (39)** plus 16 with no version recorded, while
  terminus-2 (2.0.0) and mini-swe-agent (2.4.6) were stable. On development tasks pi scores 54.9% on 1.0.1 (n=51)
  against 52.0% on 1.0.2 (n=25), 18 tasks shared — small next to the noise, but "pi" is not one harness in this data.
- `study/run_phase1.sh` now pins versions via `--ak version=...` (`V_TERMINUS2`/`V_MINI`/`V_PI`, defaulting to the
  versions most Phase 1 runs used). Every future run states its version.

### Ready to run, blocked on the OpenRouter key
- `study/queue_remaining.py` -> `study/phase2_queue.txt`: the 44 uncovered tasks x 3 harnesses x 3 repeats = 396
  runs, about $7 and 14 h of wall-clock at `PARALLEL=3`, which completes 89-task coverage.
- `study/run_live_router.sh <task> [router]`: one live Harbor run of the router's choice with the version pinned,
  appending to `study/live_runs.jsonl`. Dry-run verified on all three lookup paths (Table A hit, Qwen fallback,
  default). `lookup` needs no router API call, but the executor still needs the key.

---

## 3c. Session log: 7 Oct 2026 — success table and hard-coded lookup

- `router/build_success_table.py` writes the frozen `router/success_table.json` / `.md` (sha256 `203bc53928de12c4`).
  Table A: Luna Phase 1 results on the 27 development tasks only (best harness per task, ties to the cheaper one,
  unsolved tasks default to `mini-swe-agent`; best = mini-swe-agent 11, pi 10, terminus-2 6). Table B: Qwen3-Coder
  results on all 89 tasks (different model, 1 run each), a weak hint.
- `router/table_router.py`:
  - `lookup(task)`: **hard-coded**, no model call. (1) Task in Table A -> its best Luna harness; (2) else, task in
    Table B -> `mini-swe-agent` if Qwen passed with it, otherwise the harness Qwen passed with; (3) else
    `mini-swe-agent`. Available as `--router lookup` in `router.py` and in `pick_offline.py`.
  - Check of the Qwen fallback on the 27 development tasks (fair: Qwen results predate Phase 1, other model): the
    Qwen-only rule scores 64.2% vs 61.7% for always `mini-swe-agent`, from 3 tasks it moves off mini-swe-agent
    (`cancel-async-tasks`, `count-dataset-tokens` -> terminus-2; `crack-7z-hash` -> pi). Small and noisy, but in
    the right direction. On the 18 test tasks it changes 2 picks: `mailman` -> terminus-2,
    `model-extraction-relu-logits` -> pi.
  - `pick(...)`: LLM version (Jev or Luna) that uses Table A by exact match or analogy, Table B to break ties.
    Not run yet: OpenRouter returned **401 Unauthorized** for every call on 7 Oct (key disabled or out of credit;
    `.env` unchanged since 18 Sep). No cost incurred.
- Development-set score of `lookup`: 75.3%, +13.6 points over always `mini-swe-agent` — **identical to perfect
  picking by construction**, because the table is built from those same runs (labelled "in-sample" in the
  analysis). On the test tasks it is "always mini-swe-agent" except the 2 Qwen-based picks above, so the test set
  measures only the Qwen fallback.

## 3b. Session log: 5 Oct 2026 — Phase 1 finished, development-set results

### Runs
- 399 of 405 slots have a result. The 6 missing are pi and mini-swe-agent on `qemu-startup` (their install step
  fails in that container; 3 attempts each). 453 attempts in total including retries and the 3 set-aside runs.
- Cost: $8.42 for all runs (of which $0.24 on attempts that broke before grading), $0.66 for the 270 router picks,
  $0.03 for Luna's harness research. Total about $9.1, about twice the $4 projected (more retries and some long
  `terminus-2` runs, e.g. `path-tracing` $0.128 and `winning-avg-corewars` $0.107 per run).

### Development set (27 tasks x 3 harnesses x 3 repeats, all complete)
Baseline = best single harness on the development set = `mini-swe-agent`.

| Strategy | Pass % | vs baseline (95% CI) | Cost | $/pass | Cost/pass vs baseline |
|---|---|---|---|---|---|
| always terminus-2 | 60.5 | −1.2 [−11.1, +8.6] | $0.679 | $0.042 | +86% |
| **always mini-swe-agent** | **61.7** | baseline | $0.373 | $0.022 | 0% |
| always pi | 54.3 | −7.4 [−21.0, +7.4] | $0.314 | $0.021 | −4% |
| random | 58.8 | −2.9 [−9.9, +4.5] | $0.455 | $0.029 | +28% |
| perfect picking | 75.3 | **+13.6 [+4.9, +23.5]** | $0.511 | $0.025 | +12% |
| router: jev (profiles) | 56.8 | −4.9 [−16.0, +7.4] | $0.546 | $0.036 | +59% |
| router: luna-profiles | 58.0 | −3.7 [−13.6, +8.6] | $0.404 | $0.026 | +15% |
| router: luna-cards | 58.0 | −3.7 [−11.1, +1.2] | $0.381 | $0.024 | +9% |

- **Go/no-go: GO.** Perfect picking is 13.6 points over the best single harness, with the CI above 0, so the
  harness choice does matter on these tasks.
- **No router captures that headroom.** All three are 3.7–4.9 points *below* always using `mini-swe-agent`, and none
  meets either success criterion. Jev with profiles is the most expensive (+59% cost per pass), mostly because it
  picks `pi`/`terminus-2` where `mini-swe-agent` is cheaper.
- **Noise is high.** Only 50 of 81 task x harness cells give the same result on all 3 repeats. Part of the
  perfect-picking gap is luck in hindsight; the test set is the real check.
- Raw table: `study/phase1_results_dev.json`; everything is in `study/ilab_experiments.xlsx` (see below).

### Test set exposure (disclosed)
When the retry pass ended, `study/run_phase1.sh` printed its old end-of-run summary (`router/outcomes.py`), which
shows pass rates for **every** task, including the 18 sealed test tasks (mixed with pre-study runs, so not the
Phase 1 numbers). It was seen in the agent session. No router, profile or pick was changed afterwards: the
profiles (`571147c38da306ef`) and all 270 picks were frozen on 3–4 Oct. Logged in `study/test_unseal_log.jsonl`.
The run script now prints only a progress count.

### Experiment export
`study/export_experiments.py` writes `study/ilab_experiments.xlsx` and `study/ilab_phase1_runs.csv`. Sheets:
Notes, Phase1 runs (one row per attempt, with tokens, cost, timings, errors and whether it counts), Task x harness,
Strategies, Router picks (with reasons), Failures (by harness), Older runs (pre-study). Test-set rewards show
"sealed" until it is run with `--unseal` (logged like the analysis).

## 3a. Session log: 3 Oct 2026

### Jev study withdrawn
The Jev results in section 3.5 (offline 21 tasks, live 3 tasks, live 5-task pilot) are **withdrawn**. They used
Jev only as a drop-in replacement for Luna as the picker, with the hand-written cards, which is not the intended
design. The `routed-jev-*` job folders are kept but excluded from all results.

### New router design: Luna researches the harnesses, Jev picks
- **Research (once, blind):** `router/harness_research.py` gives Luna the source code of each harness: Harbor's
  wrappers, plus the mini-swe-agent 2.4.6 (PyPI) and pi 0.85.1 (npm, `@earendil-works/pi-coding-agent`) packages
  Harbor installs in the container, downloaded to `~/.cache/ilab_harness_src`. That is 120k / 65k / 147k
  characters. No task names, task text or results. One Luna call per harness, then one call comparing the three.
  Cost **$0.03**.
- **Profiles:** `router/harness_profiles.json` (readable copy `router/harness_profiles.md`), frozen on 3 Oct with
  content hash `571147c38da306ef`. Key differences Luna found in the code:
  - terminus-2: persistent tmux shell driven by keystrokes; interactive programs and background processes persist;
    waits capped at 60 s per command batch; 10 KB observations; context summarisation.
  - mini-swe-agent: each command is a fresh subprocess; **30-second timeout per command** (process group killed);
    no persistent cwd or variables; no interactive programs; no context compaction.
  - pi: read / write / exact-edit / grep / find / ls / bash tools; bash has **no default timeout**; can read
    images; automatic context compaction; no persistent shell.
  - Two claims were checked against the source: mini-swe-agent `LocalEnvironment.timeout = 30`, and pi bash only
    times out when a timeout is passed.
- **Picking:** `router/profile_router.py`. Jev (`typesafe/jev-router`) gets only the frozen profiles plus the task
  text and returns a harness and reason. No hand-written rules, no default harness; `max_tokens` capped. The
  profile hash, the underlying model and the cost are logged per pick. Wired into `router.py` as `--router jev`, and
  `--router luna-profiles` for the comparison.
- **Picks made before any Phase 1 result was known** (`router/pick_offline.py` -> `router/picks_profiles.json`;
  45 tasks x 2 repeats):

| Router | terminus-2 | mini-swe-agent | pi | Repeats agree | Routing cost |
|---|---|---|---|---|---|
| Jev + profiles | 9 | 14 | 67 | 42/45 tasks | $0.57 (all calls went to GPT-6.1 Sol) |
| Luna + profiles | 11 | 18 | 61 | 42/45 tasks | $0.07 |
| Luna + hand-written cards (old router) | 2 | 73 | 15 | – | $0.01 |

  The profiles move both routers from `mini-swe-agent` to `pi`, mainly because of the 30-second command timeout.
  On the earlier 21 tasks `pi` was the weakest single harness (11.67 vs 13.0), so Phase 1 will show whether the
  profile-based reasoning holds up. The profiles were not changed after seeing this; they stay frozen.

### Early hint from the old runs (not the study result)
`study/analyze_phase1.py --jobs-glob 'jobs/*'` scores the 3 Oct picks against the earlier Luna runs (21 development
tasks with all 3 harnesses, mostly 1 run per cell, includes the withdrawn `routed-jev-*` runs as outcome data):

| Strategy | Pass % | vs terminus-2 (95% CI) | Cost per pass |
|---|---|---|---|
| Perfect picking | 75.8 | +15.1 [+2.4, +30.2] | $0.015 |
| **Jev + profiles** | **65.1** | +4.4 [-10.7, +19.8] | $0.028 |
| Luna + profiles | 61.9 | +1.2 [-13.1, +15.5] | $0.020 |
| Always terminus-2 | 60.7 | – | $0.040 |
| Always mini-swe-agent | 60.3 | -0.4 [-15.1, +14.3] | $0.018 |
| Luna + cards (old router) | 57.9 | -2.8 [-17.9, +12.7] | $0.020 |
| Always pi | 55.6 | -5.2 [-25.0, +14.7] | $0.021 |

Jev + profiles is the first router above every single harness on these tasks, but the interval is wide and the
data are single runs; Phase 1 (3 repeats, unseen test set) decides.

### Phase 1 started (3 Oct, 20:55)
`study/run_phase1.sh` launched with Luna fixed (405 runs). The first runs finished with rewards, so the pipeline
works. `study/analyze_phase1.py` scores everything (checked on synthetic data with known answers).

### Issues
- iCloud has offloaded most of the project again: 11,522 files in `router/.venv`, 217 of 274 `result.json` files
  in `jobs/`, about 4,600 others. Reads block until each file downloads. New scripts are standard-library only
  so they don't need the venv. **Set the iLab folder to "Keep Downloaded"** (or move it out of iCloud).
- The earlier overnight launch with `nohup` from Cursor died within seconds; no results were lost.

### Overnight run, 4–5 Oct
- Resumed 4 Oct 23:18. The laptop was on battery and went to sleep at 00:46 (1% charge) until it was plugged
  in at 09:49, so only about 30 slots finished overnight. 342/405 slots had a reward on the morning of 5 Oct.
- 3 runs were in progress across the 9-hour sleep. They were moved (not deleted) to
  `jobs_set_aside/slept_2026-10-05/` and those slots are rerun.
- `qemu-startup` (test set): pi and mini-swe-agent fail every attempt because their own install step
  (`apt-get install`) fails in that task's container; only terminus-2 runs. **Decided before unsealing: the
  task is dropped from test-set scoring** (the analysis already drops tasks missing a harness). Report it as
  a harness reliability note.

## 3. Session log: 29 Sep 2026

### 3.1 Router prompt rewrite (`router/router2.py`, reused by `router/router.py`)
- Harness descriptions now state limits as well as strengths (for example `mini-swe-agent` runs each command in a
  fresh subprocess and cannot drive interactive programs; `terminus-2` is clumsy at writing long files by typing;
  `pi` can view images).
- Added a shared "How to decide" section (`GUIDE`) to every router prompt.
- Scoring prompt (v2) now asks for "the hardest part of the task" before scoring each harness.
- `router.py` imports `CARDS` and `GUIDE` from `router2.py`, so the Gemma, Luna and scoring prompts share one text.

### 3.2 Default harness changed to `mini-swe-agent`
- `FALLBACK` / `DEFAULT` changed from `terminus-2` to `mini-swe-agent` in `router.py`, `router2.py`,
  `gate_router.py`. Justification from independent data: best fixed harness on Qwen's 89-task baseline, and less
  than half the cost of `terminus-2`.
- `GUIDE` now says: default to `mini-swe-agent`; choose `terminus-2` only for live terminal state (interactive
  programs, servers kept alive, persistent shell session); choose `pi` only for images or substantial source
  editing; when unsure, `mini-swe-agent`.
- Offline rescoring with the old cached Luna scores (`eval_routers.py`): router v4 moved from 2.00/7 to 3.00/7 on
  held-out tasks (tied with best fixed), 10.50 to 10.00/14 on training tasks (within noise).

### 3.3 Prompt iteration experiment (`router/prompt_iterations.py`)
Method: each prompt routes the 21 tasks; each pick is scored with that task/harness's measured mean reward and
mean cost, so no Harbor runs are needed. All variants were written before any was scored. Routing cost for the
whole experiment about $0.13.

| Prompt | Expected passes (of 21) | Exec cost | Picks identical across repeats |
|---|---|---|---|
| P0 original prompt | 12.9 (2 repeats) | $0.49 | 18/21 |
| P1 limits + rules + default (current) | 13.0 | $0.23 | 21/21 |
| P2 four yes/no questions, code maps to harness | 13.0 | $0.24 | 21/21 |
| P3 plan, per-harness failure risk, then pick | 11.9 (8 repeats) | $0.24 | 7/21 |
| P4 P1 + six invented worked examples | 10.5 (2 repeats) | $0.23 | 18/21 |
| Always `mini-swe-agent` | 13.0 | $0.23 | |
| Oracle | 15.9 | $0.21 | |

- P1 ties the best fixed harness because it sends 18/21 tasks to `mini-swe-agent`; it halves cost vs P0.
- P2 was best on training tasks (11.0/14) but worst on held-out (2.0/7): noise, not signal.
- P3 first run 14.67, then averaged about 11.5 over 6 more runs; long reasoning made picks unstable and biased to `pi`.
- P4's examples pulled picks towards `pi` (about 10/21) and lowered accuracy.
- Decision: keep P1 in the router.
- Raw results: `router/prompt_iterations_results.json`, `router/prompt_iterations_results_p3_plan_risks.json`.

### 3.4 Live run
- `fix-git` through the Luna router with the new prompt and default: picked `mini-swe-agent`, **reward 1.0**.
  Routing 465 tokens / $0.0001 / 3.4 s; agent about 3 min 50 s / $0.008.
  Job: `jobs/routed-luna-fix-git-newprompt-1790661471/`.
- Total wall time about 20 min, almost all of it Python startup (see 4.1).

### 3.5 Jev Router (`typesafe/jev-router` on OpenRouter) as the harness router - WITHDRAWN (see 3a)
Jev Router is itself a model router: it picks an underlying model and reasoning effort per request. Here it
replaces Luna as the model that picks the harness (`router.py --router jev`, `prompt_iterations.py --model`).
It declares no supported parameters (temperature may be ignored) and has variable pricing.

**Offline, 21 tasks** (same method as 3.3, 2 repeats each; picks scored with measured outcomes):

| Prompt | Jev | Luna |
|---|---|---|
| P0 original | 12.42 | 12.9 |
| P1 limits + rules + default | 11.5 | 13.0 |
| P2 checklist | 12.5 | 13.0 |

- Jev never beat Luna or the best fixed harness (13.0). It picked `pi` more often (6–8 of 21 with P1 vs 3 for Luna).
- Routing cost $0.016–0.025 per 21 tasks, about 5–7x Luna. Jev sent 93 of 126 calls to DeepSeek v4.1 Flash,
  26 to GPT-6 Sol, 4 to Gemini 3.8 Flash, 3 to Claude Sonnet 5.5.
- Raw results: `router/prompt_iterations_results_p0_original_p1_rules_p2_checklist_jev-router.json`.

**Live, 3 tasks where the harness choice matters** (Jev + P1 prompt, executor Luna, 1 run each):

| Task | Measured (t2 / mini / pi) | Jev pick | Result | Exec cost |
|---|---|---|---|---|
| count-dataset-tokens | 0 / 0 / 1 | mini-swe-agent | 0.0 | $0.008 |
| constraints-scheduling | 1 / 1 / 0 | mini-swe-agent | 1.0 | $0.003 |
| schemelike-metacircular-eval | 0 / 1 / 0 | pi | 0.0 | $0.050 |

Jev live: **1/3**, routing $0.0056 total (3.7–4.9 s per pick). Same 3 tasks, other strategies (expected passes
from measured outcomes): fixed `mini-swe-agent` 2, Luna P1 2 (picks mini/mini/mini), Luna P2 1, Luna P0 1.5,
fixed `terminus-2` 1, fixed `pi` 1, oracle 3. Older live Luna routing on these tasks: count-dataset-tokens
`terminus-2` 0.0, constraints-scheduling `terminus-2` 1.0, schemelike run had no reward (errored).

Conclusion: Jev Router adds cost and variability without better harness picks. Its one distinctive pick
(`pi` for schemelike-metacircular-eval) was wrong. Not recommended as the harness router.

**Live pilot, 5 tasks** (Phase 0 of `STUDY_PLAN.md`; Jev + current prompt picks, Luna executes, 1 run each,
jobs `routed-jev-*-jevpilot5-*`). The tasks are the 5 from the 8-task pilot where harnesses differ.

| Task | Measured mean (t2 / mini / pi) | Jev pick | Result | Exec cost | Old Luna router pick (result) |
|---|---|---|---|---|---|
| build-cython-ext | 1 / 0 / 1 | mini-swe-agent | 0.0 | $0.016 | mini-swe-agent (0) |
| constraints-scheduling | 1 / 1 / 0 | mini-swe-agent | 1.0 | $0.002 | terminus-2 (1) |
| count-dataset-tokens | 0 / 0 / 1 | mini-swe-agent | 0.0 | $0.005 | terminus-2 (0) |
| headless-terminal | 1 / 1 / 0 | pi | 0.0 | $0.013 | mini-swe-agent (1) |
| winning-avg-corewars | 1 / 0.67 / 0 | mini-swe-agent | 0.0 | $0.036 | mini-swe-agent (1) |

Measured means include these runs (Luna only; terminus-2 and pi have 1–2 runs per task, mini 2–3).

Live: **Jev 1/5**, old live Luna router 3/5. Routing cost for all 5 Jev picks was $0.0025 (2–5 s each).

Scored offline with the measured means (expected passes out of 5, execution cost for 5 tasks):

| Strategy | Expected passes | Cost |
|---|---|---|
| Oracle | 5.0 | $0.126 |
| Always terminus-2 | 4.0 | $0.125 |
| Random | 2.89 | – |
| Always mini-swe-agent (= Luna P1 picks, all mini) | 2.67 | $0.060 |
| Old Luna router live picks | 2.67 | $0.063 |
| Always pi | 2.0 | $0.085 |
| **Jev router pilot picks** | **1.67** | $0.064 |

- Jev picked `mini-swe-agent` 4 times and `pi` once; its offline P1 picks on these tasks were the same. So the new
  prompt mostly collapses Jev and Luna to the default.
- Its one non-default pick (`pi` for headless-terminal, an interactive terminal task) goes against the prompt's own
  rule, which says to use terminus-2 for live terminal state.
- winning-avg-corewars failed on `mini-swe-agent` this time after passing twice: repeat noise of the size that
  Phase 1 needs 3 repeats to average out.
- The "always terminus-2 = 4.0" result rests on 1–2 runs per task and on tasks picked because the harnesses
  differ, so it is not evidence that terminus-2 is best overall (on the 21 tasks it is 12.75 vs mini 13.0).

### 3.6 Other code changes
- `outcomes.py` and the cost table in `prompt_iterations.py` count only GPT-5.6-Luna runs, because the study holds
  the executor model fixed. This drops the one-off Qwen, DeepSeek and Mimo runs from early testing; headline numbers
  are unchanged.
- `router2.py` imports `langchain_openai` lazily inside `_call`, so its prompts can be imported without the venv.
- `router.py`: `--router jev` added (`ROUTER_MODELS` maps router name to OpenRouter model); JSON parsing of the
  router reply now tolerates text around the JSON.
- `prompt_iterations.py`: `--model` option; results record which underlying model answered.
- iCloud: reading the offloaded venv files brought them down from 6,776 to about 1,400 still offloaded;
  `gate_router.py` (needs pandas/scikit-learn) still hung at startup. Keep Downloaded is still needed.

---

## 4. Errors, issues and fixes

### 4.1 Environment / operations
| Issue | Cause | Fix / status |
|---|---|---|
| Router Python hangs or takes about 20 min to start | iCloud "Desktop & Documents" had offloaded 6,776 of 11,498 files in `router/.venv` (dataless files download one by one on read). Likely also explains the earlier "processes hung at Python start". | Right-click iLab folder in Finder, Keep Downloaded. Or move the venv/project outside iCloud. **Open** until confirmed. |
| Harbor runs fail to start | Docker Desktop not running | Start Docker (`open -a Docker`) before runs |
| mini-swe-agent `ValueError: No API key found` | `OPENROUTER_API_KEY` not exported | `set -a; . ./.env; set +a; export OPENROUTER_API_KEY` |
| Several runs launched in the same second failed | Harbor job-directory name collision | Launch runs sequentially or with distinct job names |
| Long runs froze | Mac went to sleep | Run under `caffeinate -i` |
| `langchain_openai` import broken | Empty `certifi/cacert.pem` in router venv | Reinstalled `certifi` |
| `git push` hung | `gh` keyring token invalid | Connected GitHub through Cursor; push succeeded (24 Sep) |
| Docker not running during gate-router test (22 Sep) | Same as above | Unrelated to routing logic |
| OpenRouter 402 "requires more credits" (29 Sep) | API key close to its credit limit | Top up or raise the key limit before more runs. **Open** |

### 4.2 Trial-level errors in `jobs/` (123 trials)
`AgentTimeoutError` 4, `AgentSetupTimeoutError` 2, `ValueError` 2 (missing API key), `BadRequestError` 1,
`CancelledError` 1, `NonZeroAgentExitCodeError` 1, `RewardFileNotFoundError` 1. These are infrastructure failures,
not agent mistakes; a router should retry them rather than count them as fails (not implemented yet).

### 4.3 Code / repo issues
All of the items below were **fixed on 7 Oct** (see 3e), except the one marked open.
- ~~`study/run_wd.sh` and `study/run_router_wd.sh` pass `--watchdog`, which `router.py` no longer supports~~ — moved
  to `archive/`.
- Task paths differ: `gate_router.py` uses `~/.cache/harbor/tasks/*/<task>/`, `router.py` and `router2.py` use
  `~/.cache/harbor/tasks/packages/terminal-bench/<task>/*/`. Both work on this machine. **Open**, harmless.
- ~~`router/picks_cache.json` holds picks made with the old prompt; `eval_routers.py` reuses them~~ — both archived.
- ~~Duplicates: two identical copies of `Qwen_89_Task_Comparison_2026-09-20.xlsx`; `router/router_log 2.jsonl`
  repeats the first 20 entries of `router/router_log_gemma.jsonl`~~ — the duplicates are in `archive/`.
- ~~Top sections of `GPT-5.6-LUNA-BENCHMARK-RESULTS.md` ("Terminus-2 breakthrough", "Pi is the clear winner") are
  contradicted by later sections~~ — the file now opens with a superseded notice naming each contradicted claim.

### 4.4 Methodology risks
- The 7 held-out tasks have now been looked at several times; they are no longer a clean test. New tasks are needed
  for a fair evaluation of any router change.
- Most task/harness cells have one run; one task is about 5 percentage points of the 21-task score.
- Qwen baseline is one trial per cell with a different model; harness strengths may not transfer between models.
- Rules-based keyword router (from the team meeting) reaches the ceiling in-sample because keywords were chosen
  with results in view; it needs a held-out test. Its code is not in this repo yet.

---

## 5. Data inventory

- `jobs/`: 123 trials, 25 tasks; 120 with GPT-5.6-Luna, 1 each with Qwen3-Coder 480B, Mimo v2.5 Pro,
  DeepSeek v4.1 Flash. Total recorded agent cost about $2.06 (before 29 Sep).
- `Qwen_89_Task_Comparison_2026-09-20.xlsx`: Qwen3-Coder 480B, 4 harnesses, 1 trial each, 89 tasks.
  Sheets: Results, Tokens and cost, Variability, Trial details. Passes: mini-SWE 28, Terminus-2 22, OpenCode 18,
  pi 16. 54 tasks passed by no harness.
- `router/router_log.jsonl`: routing decisions (Gemma, Luna, gate).
- `router/archive_watchdog/`: watchdog code and replay results (dropped experiment).
- Terminal-Bench `task.toml` files include `category`, `tags`, `difficulty`, expert/junior time estimates: a
  possible structured routing signal (not used yet).

---

## 6. Earlier history (18–22 Sep, summary)

- **Pilot:** Luna + each harness on 5 easy tasks; all harnesses solved almost everything, so no room for routing.
- **Gemma 270M router:** picks driven by list position; after voting over all orderings it never voted for
  `terminus-2`. Dropped as too weak.
- **Luna router:** spread picks across harnesses, negligible cost (about 1–2% of execution), no accuracy gain.
- **8-task random pilot (seed 42):** router 5/8 = random, below `terminus-2` 6/8, oracle 7/8.
- **Watchdog (early stopping):** caught 1/20 then 0/20 failures in replay; 0 flags live. Dropped.
- **Router v2 (scored cards):** 60% over 21 tasks, same as random and best fixed.
- **Gate router (TF-IDF + logistic regression, Qwen 89 tasks):** leave-one-out 31.5% = always `mini-swe-agent`;
  wired in as `--router gate`.

---

## 7. Next steps

The study design is in `STUDY_PLAN.md` (question, success thresholds, development / test split, phases).
`python3 study/select_tasks.py` made the split (seed 20260929: 27 development tasks, of which 25 were run before;
18 test tasks, none run before) and a 405-run queue. Phase 1 finished on 5 Oct (see 3b).

Next:
1. ~~Decide whether to score the test set now~~ — done on 7 Oct (see 3g): scored, then unsealed on purpose so the
   lookup could cover all 45 tasks. Those 45 are training data now, which makes the **remaining 44 Phase 2 tasks
   the only held-out set left**. Nothing fitted on the 45 may be tuned again before Phase 2 runs.
2. Run Phase 2: the 44 unrun tasks x 3 harnesses x 3 repeats, with the harness versions pinned. It is the only
   way left to answer RQ2, and it also doubles the sample for the feature analysis, which is currently starved
   (64 of 81 one-hot columns fire on fewer than 3 tasks).
3. Given the development result (headroom exists, routers don't find it), consider cost-aware routing or a
   router that defaults to `mini-swe-agent` and only switches on strong evidence — designed before Phase 2 runs,
   not after.
4. Check the Qwen fallback, now on by default, against Phase 2: compare each of the 2 diverted tasks
   (`compile-compcert`, `vulnerable-secret`) with mini-swe-agent's result there. On the 45 it was +2.2 points
   [−2.2, +7.4]; if Phase 2 goes against it, set `use_qwen=False`.
5. Run the best router live on a sample of Phase 2 tasks (3 repeats) to confirm the offline estimate.

Older ideas:

1. Meta-harness: package the router as a single Harbor agent so it can be benchmarked like a harness.
2. Embedding nearest-neighbour router in `cv_gate.py`, evaluated leave-one-out. Done offline with TF-IDF in
   `study/kfold_eval.py`: it is the worst strategy tested. Embeddings still untried (needs the API key).
3. ~~Add cost per pass to `eval_routers.py`~~ — cost per pass is now a first-class metric in
   `study/analyze_phase1.py` and `study/kfold_eval.py`; `eval_routers.py` is archived.
4. ~~Try Terminal-Bench metadata (category, tags, difficulty) as features~~ — done in `study/task_features.py`;
   almost no signal. For non-Terminal-Bench prompts, having an LLM generate the same fields is still untried.
5. ~~Retry infrastructure failures instead of counting them as fails~~ — done in `study/run_phase1.sh`, and
   `study/fallback_sim.py` measures what an automatic retry would buy.
6. ~~Evaluation: fresh held-out tasks, 3+ repeats per cell, confidence intervals, prompts frozen before testing~~ —
   all in place since Phase 1; k-fold cross-validation is now the main evaluation.
7. ~~Housekeeping: fix or delete the broken `study/` watchdog scripts, remove duplicates~~ — moved to `archive/`.
   The iCloud venv issue is **open** (the project is still on Desktop).

---

## 8. Changes since the initial commit (29 Sep 2026)

Pushed in `cb5f685`. Committed locally on 5 Oct (not pushed): the Luna-only filter in `outcomes.py` / `prompt_iterations.py`,
`STUDY_PLAN.md`, `study/select_tasks.py`, `study/run_phase1.sh`, `study/analyze_phase1.py`,
`study/phase1_tasks.json`, `study/phase1_queue.txt`, `router/harness_research.py`, `router/harness_profiles.json`
and `.md`, `router/profile_router.py`, `router/pick_offline.py`, `router/picks_profiles.json`, the profile routers in
`router/router.py`, Phase 1 jobs (`jobs/p1-*`, plus 3 set-aside runs in `jobs_set_aside/`),
`study/export_experiments.py` and its outputs, `study/phase1_results_dev.json`, run logs. Withdrawn but kept: 8 `routed-jev-*` jobs and the old Jev results
JSON.


- Modified: `router/router.py`, `router/router2.py`, `router/gate_router.py`, `router/router_log.jsonl`
- New: `README.md`, `PROJECT_LOG.md`, `router/prompt_iterations.py`, `router/prompt_iterations_results.json`,
  `router/prompt_iterations_results_p3_plan_risks.json`, `jobs/routed-luna-fix-git-newprompt-1790661471/`
