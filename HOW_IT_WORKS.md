# How the iLab harness router works

This is the end-to-end picture of the system as it stands on 7 Oct 2026: what happens to a task from the moment you
start a run to the moment its trace appears in Langfuse. For results and history see `PROJECT_LOG.md`; for setup
see `README.md`.

## The idea in one paragraph

Terminal-Bench tasks are solved by a language model working inside an **agent harness**: the program that gives
the model a terminal, runs its commands and feeds the output back. We use three harnesses: **terminus-2**,
**mini-swe-agent** and **pi**. The model is always the same, **GPT-5.6-Luna**. The only thing that changes is
which harness it works in, and a **router** decides that per task. The router is either **Luna** or **Jev**
(`~typesafe/jev-latest`); nothing else picks.

```
task ──► router (Luna or Jev) ──► harness (terminus-2 | mini-swe-agent | pi) ──► Luna solves it ──► tests ──► reward
```

## The pieces

| Piece | File | What it does |
|---|---|---|
| Live runner | `study/run_live_router.sh` | Runs one task end to end: run the meta-harness on Harbor, record, upload the trace |
| Meta-harness | `router/meta_harness.py`, `router/meta_route.py` | The Harbor agent: routes the task in `setup()`, then delegates to the chosen harness |
| Router | `router/table_router.py` | `pick()` asks Luna, `decide()` asks Jev; both read the success table first |
| Success table | `router/success_table.json` (+ `.md`) | Frozen results: Luna on 45 tasks (Table A), Qwen3-Coder on 89 (Table B) |
| Routing prompt | `router/table_system_prompt.txt` | Frozen system prompt built from the table; same for Luna and Jev |
| Harness profiles | `router/harness_profiles.json` | Frozen descriptions of each harness, written by Luna from their source code |
| Setup failures | `router/difficulty_table.json` | Harnesses that could not install in a task's container (from the Qwen run) |
| Harbor | `harbor` CLI | Builds the task's Docker container, installs the harness, runs it, runs the tests |
| Langfuse exporter | `study/langfuse_export.py` | Turns a finished run into one Langfuse trace |
| Secret scrubber | `study/scrub_secrets.py`, `hooks/pre-commit` | Redacts keys from anything written or committed |

Everything that defines a routing decision (the table, the prompt, the profiles) is **frozen with a hash**. Code
refuses to run if a file was edited after freezing, so a decision can always be traced back to exact inputs
(`table_sha256 c7f5166b6d395def` today).

## A live run, step by step

```bash
study/run_live_router.sh <task> [luna|jev]     # router defaults to luna
DRY_RUN=1 study/run_live_router.sh <task> jev  # route only, print the Harbor command (a non-table task still pays to route)
study/run_final.sh [task-list] [batch]         # many tasks with luna, same-harness fallback, resumable; sets BATCH=<batch>
python3 study/final_results.py                 # results table: router vs each single harness (no runs, no calls)
```

`BATCH=<name>` (set by `study/run_final.sh`) puts the batch into the job name (`live-<batch>-luna-<task>-<time>`),
the `study/live_runs.jsonl` row and a Langfuse tag `batch:<name>`. `study/preflight.sh` checks a machine first.

**Fallback.** When a first attempt ends with no reward, a crash exception or `AgentTimeoutError`,
`study/run_final.sh` calls the runner again with `FALLBACK_HARNESS`, `FALLBACK_OF` and `FALLBACK_TRIGGER`.
- Routing is skipped (the meta-harness gets `--ak force_harness=<harness>`): the route event has
  `match: fallback`, and its single step is `fallback: no routing call`.
- The fallback is a second Harbor trial, not a retry inside the agent: Harbor's agent timeout cancels the whole
  agent, so a timed-out first attempt cannot hand over from within.
- The same harness runs again.
- The row is marked `attempt: fallback`, and the Langfuse trace is tagged `attempt:fallback`.
- The task's final result is the fallback's.

### 1. Start

The script loads `.env` (API keys, never printed), fixes the executor to `openrouter/openai/gpt-5.6-luna`, pins the
harness versions (terminus-2 2.0.0, mini-swe-agent 2.4.6, pi 1.0.1) and names the job
`live-<router>-<task>-<timestamp>`. Every stage from here on is printed and appended to
`study/logs/<job>.trace.jsonl` as one JSON event (`start`, `harbor_start`, `harbor_end`, `route`, `result`,
`observability`).

### 2. Route (inside Harbor, in the meta-harness)

The router is packaged as a Harbor custom agent, `router/meta_harness.py:MetaHarness`, so Harbor runs the
meta-harness like any other agent (`--agent meta_harness:MetaHarness`, with `router/` on `PYTHONPATH`). In
`setup()` it calls `meta_route.route()` (the code below), saves the decision as `agent/route.json` in the trial,
builds the chosen harness with its pinned version through Harbor's own `AgentFactory`, and delegates `setup()`,
`run()` and the token and cost accounting to it. Harbor's `result.json` shows the agent as `meta-harness`, version
`<harness>@<version>`. The live runner reads `route.json` after Harbor finishes and logs it as the `route` event
(timestamped when the decision was made). A dry run makes the same decision outside Harbor.

Both routers follow the same two cases.

**Case A: Luna has already run this task (45 tasks, Table A).** The router answers straight from the table: the
harness with the highest pass rate over Luna's 3 runs per harness, ties going to the cheaper one. No model is
called, it costs nothing and takes no time. Example: fix-git, where all three harnesses passed 3/3, goes to
terminus-2 because it was cheapest. This is a lookup of known results, so it is reported as a cache, not as a
routing skill.

**Case B: an unknown task.** The router model reads the frozen system prompt plus the task's instruction and picks.

- **`luna`** sends it to GPT-5.6-Luna over OpenRouter chat completions and gets back JSON:
  `{"match", "reason", "harness"}`. About $0.0004 per decision.
- **`jev`** sends the same prompt as the `state` of a single `choice` question to OpenRouter's decisions endpoint
  (`/api/alpha/decisions`). Each option's criteria are the harness's frozen "choose when" description. Jev returns
  a probability per harness and the most likely one is used. Answered by `typesafe/jev-1.13-…`, about $0.0002 per
  decision.

The prompt tells the router, in order:

1. Never pick a harness that could not install in this task's container.
2. If Qwen3-Coder passed this task, prefer mini-swe-agent if it was among Qwen's passing harnesses, else Qwen's
   first one.
3. If a known task with a clear winner does the same *kind* of work (an interactive terminal, long-running
   commands, images, many file edits), use its harness.
4. Otherwise use mini-swe-agent, the best single harness overall and the cheapest.

Every decision carries a step-by-step trace (which rule fired, the evidence, tokens, cost) that lands in the
`route` event. If the reply names no valid harness, agent setup fails and the trial ends with no reward (which the
final run treats as a fallback trigger).

`typesafe/jev-router` is **not** used anywhere: it forwards requests to other models (DeepSeek V4.1 Flash,
GPT-6.1-Sol), so its answers were never Jev's.

### 3. Run on Harbor

```
PYTHONPATH=router harbor run -t terminal-bench/<task> --model openrouter/openai/gpt-5.6-luna \
  --agent meta_harness:MetaHarness --ak router=luna --job-name <job>
# fallback adds: --ak force_harness=<harness> --ak trigger=<why> --ak first_job=<job>
```

Harbor then:

1. **Sets up the environment**: builds or starts the task's Docker container (needs Docker Desktop running).
2. **Sets up the meta-harness**: routes (step 2 above), then installs the chosen harness inside the container.
3. **Runs the agent**: the harness loops, with Luna deciding the next action, the harness executing it in the
   container and feeding back the output, until Luna declares the task done or a time limit hits.
   - terminus-2 types keystrokes into a tmux terminal and reads the screen.
   - mini-swe-agent runs one bash command per step and returns its output.
   - pi has its own tool set (bash, file reads and edits) and session log.
4. **Verifies**: runs the task's hidden pytest suite. All tests passing gives reward 1, otherwise 0.

Harbor writes everything to `jobs/<job>/<task>__<id>/`: `result.json` (timings per stage, tokens, cost, reward,
exceptions), `agent/trajectory.json` (every step: messages, Luna's thinking, tool calls, outputs, tokens, cost),
`verifier/ctrf.json` and `test-stdout.txt`, and the logs (`trial.log`, the agent console). Its console output goes
to `study/logs/<job>.log`.

### 4. Record

The script reads `result.json` and the trajectory and writes a `result` event (reward, exception, agent steps,
tokens, cost, minutes per stage) and one summary line in `study/live_runs.jsonl`.

### 5. Upload to Langfuse

If the Langfuse keys are in `.env` and the observability venv exists, the script runs
`study/langfuse_export.py jobs/<job>` and records the trace link as an `observability` event. An upload failure
never fails the run. Details in the next section.

## What you see in Langfuse

Project on `jp.cloud.langfuse.com`, environment `live`. One trace per run:

```
solve-task (chain)              input: the task instruction; output: harness, reward, tests passed, cost
├─ route-task                   retriever (answered from the table) or generation (Luna/Jev call: prompt, reply,
│                               model, tokens, cost; Jev's probabilities)
├─ set-up-environment (span)    container setup
├─ <harness> (agent)            terminus-2 / mini-swe-agent / pi
│  ├─ install-harness (span)
│  ├─ decide-next-action        one generation per Luna call: messages in, reply + thinking + tool calls out,
│  │                            tokens (input, cached, output, reasoning) and cost
│  └─ <tool name> (tool)        that step's tool calls, grouped by tool name, with commands and outputs
└─ verify-solution (evaluator)  per-test results; WARNING when reward < 1
scores: reward, tests_passed
```

- **Session** = the task name, so every run of one task lines up in the Sessions view.
- **Tags** `router:`, `harness:`, `match:` for filtering and dashboards, copied onto every observation.
- **Logs** ride along as metadata, last 8,000 characters each: `log_harbor` and `log_exception` on `solve-task`,
  `log_console` on the harness, `log_pytest` on `verify-solution`.
- Built only from the files the run left behind, so exporting changes nothing about the run.
- Sent over OpenTelemetry so the real start and end times are kept. Text is clipped and scrubbed of secrets first.
- **Sent once per run.** Langfuse does not merge a re-sent trace, so `study/logs/langfuse_sent.jsonl` records what
  was sent; running the exporter again just prints the link. `--replace` deletes the old trace and sends a new one.
- **Cost of tracing:** 17 to 32 Langfuse units per run (observations + scores + trace); the free plan has 50,000 a
  month.

```bash
~/.venvs/ilab-obs/bin/python study/langfuse_export.py jobs/<job> --dry-run   # print the tree, send nothing
```

**Dashboard "iLab router: live runs"** (built by `study/langfuse_dashboard.py` through Langfuse's MCP server):
headline numbers (runs, pass rate, total spend, routing spend); pass rate and Luna calls per configuration
(router + harness + match); spend by model (Luna vs the router model); runs, failures and spend by task; where the
time goes per stage; failed commands by tool; pass rate and spend per day; Luna's token mix. Widgets cannot break
down by metadata, which is why router and harness are also tags; scores carry no session, so per-task failures
come from `verify-solution` observations at WARNING level.

## How the routing knowledge was built (offline)

The router's knowledge comes from saved benchmark runs, not from live runs:

1. **Qwen baseline** (Sep): Qwen3-Coder ran all 89 tasks once per harness. This is Table B.
2. **Phase 1** (3 to 5 Oct, `study/run_phase1.sh`): Luna ran 45 tasks, 3 times per harness. This is Table A.
3. **Evaluation** (`study/kfold_eval.py`, `study/analyze_phase1.py`): routers were scored by replaying those saved
   results, cross-validated. No router so far beats always using mini-swe-agent on unseen tasks; perfect per-task
   picking would reach about 70% against about 55%.
4. **Table** (`router/build_success_table.py --include-test`): builds and freezes the success table and writes the
   routing prompt.

**The offline rule:** the router is developed only against those saved results. Live runs are smoke tests that the
chosen harness really launches and scores; their results never feed back into the table.

## Safety

- `.env` holds the OpenRouter and Langfuse keys. It is gitignored and its values are never printed.
- The OpenRouter key reaches harnesses inside the container, so an agent can dump it into a transcript.
  `hooks/pre-commit` (enable with `git config core.hooksPath hooks`) refuses commits that contain a key, and
  `study/scrub_secrets.py --apply` redacts files that already do. The Langfuse exporter scrubs everything it sends.

## Where to look when something goes wrong

| Question | Look at |
|---|---|
| Why did a task get this harness? | `route` event in `study/logs/<job>.trace.jsonl`, or `python3 router/table_router.py --explain <task>` |
| What did the agent do? | Langfuse trace, or `jobs/<job>/*/agent/trajectory.json` |
| Why did the tests fail? | `verify-solution` in Langfuse, or `jobs/<job>/*/verifier/test-stdout.txt` |
| Did Harbor itself fail? | `study/logs/<job>.log`, `jobs/<job>/*/trial.log`, `exception_info` in `result.json` |
| All live runs at a glance | `study/live_runs.jsonl`, or the Langfuse traces table filtered by tag |

Known issues: terminus-2 sometimes gets stuck in git's `less` pager on fix-git (2 of 5 live runs failed that way);
iCloud can offload `router/.venv`, making Python start very slowly (the live runner uses the system Python, so it
is not affected).
