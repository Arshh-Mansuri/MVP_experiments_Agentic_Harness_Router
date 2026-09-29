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

### 3.5 Other code changes
- `router2.py` imports `langchain_openai` lazily inside `_call`, so its prompts can be imported without the venv.

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

### 4.2 Trial-level errors in `jobs/` (123 trials)
`AgentTimeoutError` 4, `AgentSetupTimeoutError` 2, `ValueError` 2 (missing API key), `BadRequestError` 1,
`CancelledError` 1, `NonZeroAgentExitCodeError` 1, `RewardFileNotFoundError` 1. These are infrastructure failures,
not agent mistakes; a router should retry them rather than count them as fails (not implemented yet).

### 4.3 Code / repo issues (not fixed)
- `study/run_wd.sh` and `study/run_router_wd.sh` pass `--watchdog`, which `router.py` no longer supports (watchdog
  removed and archived). They also set `TB_TASK_DIR` to a temporary path under `~/.claude/jobs/...`.
- Task paths differ: `gate_router.py` uses `~/.cache/harbor/tasks/*/<task>/`, `router.py` and `router2.py` use
  `~/.cache/harbor/tasks/packages/terminal-bench/<task>/*/`. Both work on this machine.
- `router/picks_cache.json` holds picks made with the old prompt; `eval_routers.py` reuses them. Rename/delete it
  before re-evaluating the new prompt.
- Duplicates: the two copies of `Qwen_89_Task_Comparison_2026-09-20.xlsx` are identical;
  `router/router_log 2.jsonl` repeats the first 20 entries of `router/router_log_gemma.jsonl`.
- Top sections of `GPT-5.6-LUNA-BENCHMARK-RESULTS.md` ("Terminus-2 breakthrough", "Pi is the clear winner") are
  contradicted by later sections.

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

1. Meta-harness: package the router as a single Harbor agent so it can be benchmarked like a harness.
2. Embedding nearest-neighbour router in `cv_gate.py`, evaluated leave-one-out.
3. Add cost per pass to `eval_routers.py`; treat cost as a first-class metric.
4. Try Terminal-Bench metadata (category, tags, difficulty) as features; for non-Terminal-Bench prompts, have an
   LLM generate the same fields.
5. Retry infrastructure failures instead of counting them as fails.
6. Evaluation: fresh held-out tasks, 3+ repeats per cell, confidence intervals, prompts frozen before testing.
7. Housekeeping: fix or delete the broken `study/` watchdog scripts, remove duplicates, fix the iCloud venv issue.

---

## 8. Changes since the initial commit (29 Sep 2026)

- Modified: `router/router.py`, `router/router2.py`, `router/gate_router.py`, `router/router_log.jsonl`
- New: `README.md`, `PROJECT_LOG.md`, `router/prompt_iterations.py`, `router/prompt_iterations_results.json`,
  `router/prompt_iterations_results_p3_plan_risks.json`, `jobs/routed-luna-fix-git-newprompt-1790661471/`
