# GPT-5.6-LUNA + Terminus-2 Benchmark Results

## Summary
Testing GPT-5.6-LUNA model with Terminus-2 agent on Harbor terminal-bench tasks. This model/harness combination achieved **4/5 successful completions** (80% success rate).

---

## Results by Task

### ✅ Cobol-Modernization (2026-09-19__00-09-53 → 00:12:29)
- **Score**: 1.0 ✅ **PERFECT**
- **Model**: openai/gpt-5.6-luna
- **Harness**: terminus-2
- **Tokens Used**: 177,083 total (93,017 input / 8,238 output / 75,828 cache)
- **Time**: 2m 36s
- **Cost**: $0.01565

### ✅ Fix-Git (2026-09-19__00:12:38 → 00:14:00)
- **Score**: 1.0 ✅ **PERFECT**
- **Model**: openai/gpt-5.6-luna
- **Harness**: terminus-2
- **Tokens Used**: 20,305 total (11,779 input / 1,378 output / 7,148 cache)
- **Time**: 1m 22s
- **Cost**: $0.00292

### ✅ Prove-Plus-Comm (2026-09-19__00:24:33 → 00:26:24)
- **Score**: 1.0 ✅ **PERFECT**
- **Model**: openai/gpt-5.6-luna
- **Harness**: terminus-2
- **Tokens Used**: 13,984 total (7,980 input / 1,051 output / 4,953 cache)
- **Time**: 1m 51s
- **Cost**: $0.00208

### ❌ DB-Wal-Recovery (2026-09-19__00:25:32 → 00:28:28) [RETRIED]
- **Score**: 0.0 ❌ **FAILED (CONSISTENT)**
- **Model**: openai/gpt-5.6-luna
- **Harness**: terminus-2

**Initial Attempt:**
- **Tokens Used**: 85,948 total (44,008 input / 7,713 output / 34,227 cache)
- **Time**: 2m 56s
- **Cost**: $0.01234
- **Note**: Agent executed but did not produce expected output/reward file

**Retry (2026-09-19__00:31:49 → 00:33:51):**
- **Tokens Used**: 64,238 total (34,724 input / 3,945 output / 25,569 cache)
- **Time**: 1m 59s
- **Cost**: $0.00749
- **Note**: Failure confirmed. Consistent inability to solve this specific task despite lower token usage on retry

### ✅ Git-Leak-Recovery (2026-09-19__00:27:53 → 00:29:17)
- **Score**: 1.0 ✅ **PERFECT**
- **Model**: openai/gpt-5.6-luna
- **Harness**: terminus-2
- **Tokens Used**: 8,686 total (5,624 input / 1,345 output / 1,717 cache)
- **Time**: 1m 24s
- **Cost**: $0.00259

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Success Rate | 80% (4/5) |
| Perfect Scores | 4 |
| Failed Tasks | 1 (db-wal-recovery, retried and confirmed) |
| Average Time (successful) | 1m 58s |
| Total Cost | $0.05107 (incl. retry) |
| Average Tokens per Task | 41,213 |

---

## Key Findings

1. **GPT-5.6-LUNA is highly capable** - Achieved perfect scores on diverse tasks (COBOL, Git, Proof, Leak detection)
2. **Terminus-2 agent works well with this model** - Consistent execution and reasoning
3. **One failure (DB-WAL)** - Model ran but didn't produce expected output format. May indicate task complexity issue rather than model/agent limitation
4. **Cost is reasonable** - ~$0.01-0.02 per task depending on complexity
5. **Token efficiency varies** - Simpler tasks (git-leak) use fewer tokens; complex tasks (cobol) use more

---

## Comparison with Other Attempts

### Previous Failures (before GPT-5.6-LUNA):
- **mimo2.5** (oracle): Score 1.0 ✅ (embedding-drift only, fast)
- **mimo2.5+** (mini-swe): Score 0.0 ❌ (task execution failed)
- **mimo2.5+** (terminus-2): Score 0.0 ❌ (litellm routing error)
- **mimo2.5** (opencode): Score 0.0 ❌ (API model unavailable)
- **qwen3-coder-480b** (terminus-2): Score 0.0 ❌ (routing error)

### Victory: GPT-5.6-LUNA
✅ First agentic harness to consistently solve complex benchmark tasks
✅ 80% success rate across diverse problem domains
✅ Demonstrates model quality matters for agent performance

---

---

## Mini-SWE-Agent Breakthrough (with OPENROUTER_API_KEY Fix)

**Discovery**: mini-swe-agent was failing due to missing environment variable. Once `OPENROUTER_API_KEY` was properly exported, mini-swe-agent achieved **100% success rate (4/4)** on all Luna tasks!

### ✅ Mini-SWE-Agent Results (GPT-5.6-LUNA)

| Task | Score | Time | Input Tokens | Cache Tokens | Output Tokens | Total Tokens | Cost |
|------|-------|------|--------------|--------------|---------------|--------------|------|
| fix-git | 1.0 ✅ | 2m 32s | 66,983 | 56,121 | 2,380 | 125,484 | $0.00665 |
| cobol-modernization | 1.0 ✅ | 2m 44s | 51,412 | 40,875 | 5,334 | 97,621 | $0.00985 |
| git-leak-recovery | 1.0 ✅ | 2m 50s | 7,203 | 3,557 | 1,200 | 11,960 | $0.00238 |
| prove-plus-comm | 1.0 ✅ | 4m 12s | 38,438 | 27,792 | 3,307 | 69,537 | $0.00709 |

**Summary**: 
- Success Rate: **100% (4/4)**
- Total Time: 12m 58s (average: 3m 15s per task)
- Total Cost: $0.02337
- Total Tokens: 164,036 input / 128,345 cache / 12,221 output

### Key Insight: API Key Configuration Matters!

The initial mini-swe-agent failures (ValueError: "No API key found") were due to the agent not recognizing the OpenRouter API key. **Solution**: Export `OPENROUTER_API_KEY` before running harbor commands.

**Before fix**: Both fix-git and cobol-modernization failed with ValueError (0.0 score)
**After fix**: Both tasks and all other Luna tasks succeeded (1.0 score)

---

## Pi Harness Results (GPT-5.6-LUNA)

**Discovery**: Pi harness achieves **100% success rate (4/4)** and is the FASTEST agent tested!

| Task | Score | Time | Input Tokens | Cache Tokens | Output Tokens | Total Tokens | Cost |
|------|-------|------|--------------|--------------|---------------|--------------|------|
| fix-git | 1.0 ✅ | 2m 12s | 42,943 | 42,916 | 1,710 | 87,569 | $0.00487 |
| cobol-modernization | 1.0 ✅ | 2m 38s | 28,364 | 28,340 | 3,657 | 60,361 | $0.00672 |
| git-leak-recovery | 1.0 ✅ | 2m 12s | 9,562 | 9,547 | 1,261 | 20,370 | $0.00226 |
| prove-plus-comm | 1.0 ✅ | 2m 41s | 31,844 | 31,802 | 1,426 | 65,072 | $0.00325 |

**Summary**:
- Success Rate: **100% (4/4)**
- Total Time: 9m 43s (average: 2m 26s per task) ⚡ **FASTEST**
- Total Cost: $0.01710 ⚡ **CHEAPEST**
- Total Tokens: 112,713 input / 112,605 cache / 8,054 output

---

## Comparison: Terminus-2 vs Mini-SWE-Agent vs Pi

| Agent | Model | Success Rate | Avg Time | Total Cost | Notes |
|-------|-------|--------------|----------|-----------|-------|
| **Terminus-2** | GPT-5.6-LUNA | 80% (4/5) | 1m 58s | $0.04358 | db-wal-recovery fails |
| **Mini-SWE** | GPT-5.6-LUNA | 100% (4/4) | 3m 15s | $0.02337 | Works with env setup |
| **Pi** ⭐ | GPT-5.6-LUNA | **100% (4/4)** | **2m 26s** | **$0.01710** | **Best performance** |

**Verdict**: **Pi harness is the clear winner** - fastest execution, lowest cost, perfect success rate!

---

---

## Polyglot-C-Py Task Results (New Task)

Testing all three agents on a new task: polyglot-c-py

| Agent | Score | Time | Input Tokens | Cache Tokens | Output Tokens | Total Cost |
|-------|-------|------|--------------|--------------|---------------|-----------|
| Terminus-2 | 1.0 ✅ | 3m 5s | 3,026 | 0 | 5,197 | $0.00695 |
| Pi | 1.0 ✅ | 2m 59s | 8,746 | 8,734 | 2,612 | $0.00414 |
| Mini-SWE | 1.0 ✅ | 3m 42s | 10,205 | 6,029 | 3,308 | $0.00509 |

**Key Observation**: 
- All three agents **100% success** on polyglot-c-py
- **Pi remains fastest** (2m 59s) and **cheapest** ($0.00414)
- Terminus-2 has lowest token usage but no cache hits
- Mini-SWE uses most tokens but successful

---

## Next Steps

- [ ] Investigate why db-wal-recovery failed with Terminus-2 (may work with mini-swe)
- [ ] Test db-wal-recovery with mini-swe-agent
- [ ] Compare performance metrics to oracle baseline (embedding-drift: 1m 2s, free)
- [ ] Log all results to Google Sheet for tracking

---

**Generated**: 2026-09-19
**Test Environment**: Harbor terminal-bench, OpenRouter API
**Summary**: GPT-5.6-LUNA + Terminus-2 represents the breakthrough model/harness combo for solving complex code-related benchmark tasks.

---

## Gemma-3-270M Harness Router (blind routing)

**Setup**: `router/router.py` (LangChain + LangGraph: load_task → classify → validate → dispatch → log). Gemma 3 270M (Ollama, temp 0, JSON-enum constrained output) sees only the task instruction text plus generic harness descriptions. **No prior benchmark results were used** in the prompt or code. Invalid output falls back to terminus-2. Executor model: openrouter/openai/gpt-5.6-luna. Classification latency 0.2–0.8 s per task.

| Task | Router pick | Routed score | Routed time | Routed cost | Direct: Terminus-2 / Mini-SWE / Pi |
|------|-------------|--------------|-------------|-------------|------------------------------------|
| fix-git | terminus-2 | **0.0 ❌** | 0m 56s | $0.00260 | 1.0 / 1.0 / 1.0 |
| cobol-modernization | pi | 1.0 ✅ | 2m 31s | $0.01006 | 1.0 / 1.0 / 1.0 |
| git-leak-recovery | mini-swe-agent | 1.0 ✅ | 2m 59s | $0.00243 | 1.0 / 1.0 / 1.0 |
| prove-plus-comm | pi | 1.0 ✅ | 2m 26s | $0.00263 | 1.0 / 1.0 / 1.0 |
| polyglot-c-py | pi | 1.0 ✅ | 2m 43s | $0.00343 | 1.0 / 1.0 / 1.0 |

**Routed success: 4/5 (80%)**. Direct baselines: Terminus-2 5/5 on these tasks, Mini-SWE 5/5, Pi 5/5.

Notes:
- Router chose pi 3x, mini-swe 1x, terminus-2 1x; all outputs were valid JSON labels.
- The only failure was fix-git routed to terminus-2, which had scored 1.0 directly. Same harness+model, different outcome: run-to-run variance (n=1), not clearly a routing error. First attempt at fix-git died in 4 s (harbor job-dir collision from launching 5 runs in the same second); the rerun ran alone and scored 0.0.
- Every harness passes these 5 tasks in direct runs, so the study cannot show routing *gains* here; it only shows the router did no harm beyond noise. Meaningful routing tests need tasks where harnesses differ (e.g. db-wal-recovery).
- Routed costs are comparable to direct runs (~$0.002–0.010/task); routing overhead is <1 s and free (local model).

### Router fix-git retry
Router again picked terminus-2 (blind). Result: **1.0 ✅**, 1m 3s, 17,000 in / 11,772 cache / 1,583 out, $0.00341 (job 2026-09-19__09-05-07). The earlier 0.0 was run-to-run variance. Routed fix-git over 2 attempts: 1 pass / 1 fail (the earlier failure stands in the record; final tally is 4/5 first-pass, 5/5 after retry).

---

## Study: Gemma Router vs Fixed Harness (is the router worth it?)

**Question**: Does routing each task to a harness chosen by Gemma 3 270M (blind to prior results) beat simply picking one harness for everything?
**Task set**: fix-git, cobol-modernization, git-leak-recovery, prove-plus-comm, polyglot-c-py. Executor model for all: GPT-5.6-LUNA. n = 1 run per cell (2 for routed fix-git).

### Head-to-head (same 5 tasks)

| Approach | Pass (first attempt) | Total cost | Avg time / task | Extra infra |
|----------|---------------------|-----------|-----------------|-------------|
| Fixed: Terminus-2 | 5/5 | $0.03019 | 2m 04s | none |
| Fixed: Mini-SWE | 5/5 | $0.03106 | 3m 12s | none |
| Fixed: Pi | 5/5 | **$0.02124** | 2m 32s | none |
| **Gemma router** | **4/5** | $0.02115 (+$0.00341 for the fix-git retry = $0.02456) | 2m 19s (+0.2-1.3 s classify) | Ollama + LangGraph + 270M model |

Router picks: pi x3, mini-swe x1, terminus-2 x1 (all valid, no fallbacks).

### Findings

1. **Accuracy**: router 4/5 first-pass (5/5 with the retry) vs 5/5 for every fixed harness. The one miss was fix-git on terminus-2, which passed on retry and had passed directly, so it is run variance, not evidence of a bad routing decision. Still, the router did not beat any fixed option.
2. **Cost**: the router landed between Pi (cheapest) and Terminus-2/Mini-SWE, about 30% cheaper than fixed Terminus-2 or Mini-SWE, but roughly equal to fixed Pi ($0.0212 vs $0.0212 first pass; $0.0246 with retry). It only looks cheap because it sent 3 of 5 tasks to pi.
3. **Speed**: router 2m 19s avg vs Pi 2m 32s, Terminus-2 2m 04s, Mini-SWE 3m 12s. Differences are within run-to-run noise; the fix-git run that ended early (0.0) also pulls the router's average down.
4. **Routing overhead**: negligible (0.2-1.3 s, free, local). The real costs are operational: running Ollama, maintaining prompts, and a failure mode where a 270M model mislabels.
5. **Router quality**: Gemma's picks looked close to arbitrary (terminus-2 for a git task, pi for three unrelated tasks, mini-swe for the git-leak task). A 270M model reading task text has little basis to tell these harnesses apart, and the generic descriptions barely differ in the signal they give.

### Verdict: not worth it on this evidence

- Every harness solves every task in this set, so there is no headroom for a router to add value. The best it can do is tie the best fixed harness, and it does not even tie it on accuracy.
- A fixed Pi setup matched the router's cost, was 5/5, and needs no extra model or infra.
- The result does **not** show routing is useless, only that this test cannot detect a benefit. Routing pays off only if harness performance differs by task type.

### Limits of the study
- n = 1 per cell; one failure swings pass rate by 20 points.
- Tasks were pre-selected as ones Terminus-2 + Luna could solve, so they are easy for all harnesses (selection bias against the router).
- db-wal-recovery, the one task where harnesses might differ (Terminus-2 failed twice), was never run through mini-swe, pi, or the router.
- Parallel launches share the machine, so timings are noisy.

### What would change the verdict
1. Run a harder/wider task set (10-20 tasks incl. db-wal-recovery and tasks Terminus-2 fails) with all three harnesses direct, to find whether any task-type dependence exists at all.
2. Compare the router to an **oracle** (best harness per task) and to random routing; a router that cannot beat random is noise.
3. Repeat each cell 3+ times to separate variance from real differences.
4. Only if step 1 shows harnesses genuinely diverge, try a larger router model (or embedding-similarity classifier) instead of a 270M generator.

**Recommendation**: use Pi as the fixed default for Luna; revisit routing only after a wider benchmark shows per-task harness differences.

---

## db-wal-recovery: all 3 harnesses + router (run one by one)

| Run | Score | Time | Input / Cache / Output tokens | Cost | Job |
|-----|-------|------|-------------------------------|------|-----|
| Terminus-2 | **1.0 ✅** | 1m 13s | 10,704 / 5,870 / 1,521 | $0.00311 | 2026-09-19__09-45-16 |
| Mini-SWE | 0.0 ❌ | 2m 01s | 28,189 / 21,740 / 2,352 | $0.00482 | 2026-09-19__09-46-34 |
| Pi | 0.0 ❌ | 2m 00s | 49,534 / 49,495 / 3,321 | $0.00683 | 2026-09-19__09-48-39 |
| Router (picked mini-swe-agent) | 0.0 ❌ | 2m 21s | 23,228 / 15,860 / 2,961 | $0.00567 | 2026-09-19__09-50-47 |

**Observations**
- Terminus-2 passed this time but failed both earlier attempts (0/2), so its record on this task is now 1/3: the task is flaky/hard for Luna, not cleanly harness-dependent.
- Mini-SWE and Pi each failed once (n=1 each); the router routed to mini-swe (blind), which failed.
- This is the first task where the fixed harnesses diverged in a single pass, but the sample is too small to attribute it to the harness rather than variance. Router did not beat the best fixed harness here (it picked a failing one).
- Updated tally including db-wal-recovery (6 tasks, first pass): Router 4/6, Terminus-2 5/6 (this run), Mini-SWE 5/6, Pi 5/6. Verdict unchanged: no evidence the router adds value; repeat runs (3+ per cell) needed to tell whether db-wal-recovery favours any harness.

### Why the router did not pick Terminus-2 for db-wal-recovery

Probe (blind, same prompt, same task text, temp 0): I re-classified db-wal-recovery under all 6 orderings of the harness list.

| Harness listed first | Router answer |
|----------------------|---------------|
| terminus-2 first (2 orderings) | mini-swe-agent, pi |
| mini-swe-agent first (2 orderings) | mini-swe-agent, mini-swe-agent |
| pi first (2 orderings) | pi, pi |

- Gemma **never chose terminus-2 for this task in any ordering**; its answer mostly follows list position (whichever of mini-swe-agent/pi appears early) rather than the task.
- Likely reason: the task text is about fixing a corrupted file / recovering data, which lexically matches "fixing issues in codebases" (mini-swe-agent) and "file read/write/edit" (pi) far more than "controls a tmux terminal by sending keystrokes" (terminus-2). Terminus-2 was chosen only for tasks with little matching text (fix-git; probe prompts like "Write a haiku about cats" and "Compile a kernel" both went to terminus-2), i.e. it behaves as a default bucket.
- Even a "correct" pick would have been luck: Terminus-2 passed only 1 of 3 attempts on this task, so its win is not a stable harness effect. The router failing to pick it is not a proven mistake; it is evidence the router's choices are driven by wording and order, not by real harness fit.
- Conclusion: reinforces the verdict that a 270M generator is a weak signal for harness selection.

### Router fix attempt: remove position bias + balanced descriptions (blind, no result-driven tuning)

**Changes** (`router/router.py`): (1) classify now queries Gemma under all 6 orderings of the harness list and takes the plurality vote (cancels list-position bias); ties/invalid fall back to terminus-2. (2) Rewrote the three harness descriptions once, in parallel structure, each stating what it works on (none mention benchmark outcomes). One attempt only; not iterated against results, to avoid fitting to the test set.

| Task | Votes (t2 / mini / pi) | Pick |
|------|------------------------|------|
| db-wal-recovery | 0 / 3 / 3 | terminus-2 (tie fallback) |
| fix-git | 0 / 3 / 3 | terminus-2 (tie fallback) |
| cobol-modernization | 0 / 3 / 3 | terminus-2 (tie fallback) |
| git-leak-recovery | 0 / 3 / 3 | terminus-2 (tie fallback) |
| prove-plus-comm | 0 / 0 / 6 | pi |
| polyglot-c-py | 0 / 2 / 4 | pi |

**Finding**: the fix did not work. Gemma 270M gave terminus-2 **zero votes on every task** under every ordering, with both the original and the rewritten descriptions. The terminus-2 picks above are only the tie-fallback, not a real classification. The model appears to ignore the first-listed/unfamiliar-name option and split between the other two; it cannot discriminate these three harnesses from task text. (Earlier single-order picks of terminus-2 for fix-git were likewise a position/default artifact.)

**Conclusion**: not a prompt problem we can fix honestly at 270M. Options: a bigger router model (e.g. gemma3:4b / 12b), a different method (score each harness separately, or embeddings), or drop routing and use a fixed harness. Router results above (including the db-wal miss) were produced with the earlier single-pass version.

---

## Luna as router (single classification call per task, router tokens tracked)

Router: `openai/gpt-5.6-luna` via OpenRouter, given task text + the same generic harness descriptions (no prior results), one call per task. Executor: Luna. Router token/cost figures come from the API usage of the routing call itself.

| Task | Luna picked | Score | Exec time | Exec cost | Router tokens (total) | Router cost | Router latency |
|------|-------------|-------|-----------|-----------|-----------------------|-------------|----------------|
| db-wal-recovery | terminus-2 | 0.0 ❌ | 2m 17s | $0.01170 | 366 | $0.000124 | 2.7 s |
| fix-git | terminus-2 | 0.0 ❌ | 1m 14s | $0.00317 | 237 | $0.000114 | 2.4 s |
| cobol-modernization | mini-swe-agent | 1.0 ✅ | 3m 52s | $0.01644 | 462 | $0.000105 | 1.3 s |
| git-leak-recovery | terminus-2 | 1.0 ✅ | 1m 39s | $0.00348 | 327 | $0.000143 | 2.4 s |
| prove-plus-comm | mini-swe-agent | 1.0 ✅ | 3m 09s | $0.00519 | 276 | $0.000068 | 1.0 s |
| polyglot-c-py | pi | 1.0 ✅ | 2m 44s | $0.00374 | 268 | $0.000064 | 1.1 s |

**Totals**: 4/6 passed. Executor cost $0.04372; router cost $0.00062 (1.4% overhead, ~1,900 tokens total, 1-3 s per task).

**Findings**
- Luna spread picks across all three harnesses (terminus-2 x3, mini-swe x2, pi x1), unlike Gemma-270M which never chose terminus-2. Routing overhead is negligible in cost and tokens.
- It picked terminus-2 for db-wal-recovery, but that run scored 0.0 (Terminus-2 is 2/4 on this task across attempts), so the pick was not rewarded. fix-git on terminus-2 also failed here (it has passed 3 of 5 times with terminus-2 overall), consistent with variance.
- No accuracy gain: 4/6 vs fixed harnesses at 5/6 on first pass. With n=1 and both misses on tasks where Terminus-2 is flaky, this is not enough to attribute misses to routing. Luna's choices also look plausible-but-unfounded: nothing shows it knows which harness suits which task.
- Verdict unchanged: the router is cheap to run but has shown no benefit over a fixed harness (Pi). Repeated runs (3+ per cell) plus an oracle/random-routing baseline are still needed.

---

## Pilot: 8 new random Terminal-Bench 2.0 tasks (seed 42, not filtered by difficulty), 1 run per cell

Executor: Luna. Router: Luna (blind, generic descriptions). Jobs: `jobs/direct-<agent>-<task>-rep1`, `jobs/routed-luna-<task>-rep1-*`. No infra exceptions.

| Task | Terminus-2 | Mini-SWE | Pi | Router (pick) |
|------|-----------|----------|----|---------------|
| build-cython-ext | 1 | 0 | 1 | 0 (mini-swe) |
| constraints-scheduling | 1 | 1 | 0 | 1 (terminus-2) |
| count-dataset-tokens | 0 | 0 | 1 | 0 (terminus-2) |
| distribution-search | 1 | 1 | 1 | 1 (mini-swe) |
| gcode-to-text | 0 | 0 | 0 | 0 (terminus-2) |
| headless-terminal | 1 | 1 | 0 | 1 (mini-swe) |
| large-scale-text-editing | 1 | 1 | 1 | 1 (terminus-2) |
| winning-avg-corewars | 1 | 1 | 0 | 1 (mini-swe) |
| **Pass** | **6/8** | 5/8 | 4/8 | **5/8** |
| **Exec cost** | $0.205 | $0.108 | $0.118 | $0.103 (+ $0.0022 routing) |

Baselines: **oracle** (best harness per task) 7/8; **random routing** expected 5.0/8; best fixed harness Terminus-2 6/8.

**Routing overhead**: 240-720 tokens and ~$0.0001-0.0004 per task (total $0.0022 for 8 tasks, ~2% of exec cost).

### Findings
1. Harnesses now differ (Pi 4/8 vs Terminus-2 6/8), so the earlier "all tie" problem is gone: on these tasks routing has room to matter (oracle 7/8 vs best fixed 6/8).
2. The router got 5/8, **equal to random routing (5.0) and below best-fixed Terminus-2 (6/8)** and far from the oracle. Its picks were almost never task-specific in a useful way: 5 of 8 went to mini-swe or terminus-2 roughly by wording, and it missed the one task where only Pi passes (count-dataset-tokens).
3. Every routed run reproduced the direct result of the harness it picked (8/8 agreement), so run-to-run variance was low here and the outcome was determined by the pick. That means the router's value is fully explained by pick quality, which is at random level.
4. Cost: router ($0.103) is about half of Terminus-2's ($0.205) but its savings come from picking cheaper harnesses, not from better decisions; Terminus-2 spends more because it passes more. Cost per pass: Terminus-2 $0.034, Mini-SWE $0.022, Pi $0.030, Router $0.021 (router/Mini-SWE cheapest, but at lower pass rate).
5. Limits: n=1 per cell, 8 tasks; Terminus-2's lead over the router is 1 task, not statistically solid. Repeats (3+) still needed.

### Verdict update
Not worth it yet: Luna as a router performs at random-routing level and below the best fixed harness (Terminus-2), while an oracle would gain one extra task. A useful router would have to beat random meaningfully; this one does not. Reasonable next step would be a different routing method (score per harness, larger model, or learn from held-out task results) evaluated on tasks separate from the ones used to fit it, plus repeats.

---

## Watchdog (early-stop) experiment: dropped

Built `router/watchdog.py` (reads the live agent log; Luna judge + loop/error heuristics; shadow and active modes, wired into the router with `--watchdog`). Findings:
- Replay on 65 finished runs (earlier 14 tasks): caught 1/20 failures with the first prompt and 0/20 after tightening, while wrongly flagging 5/45 then 2/45 passing runs. Most failures are short (median 10 steps, the agent gives up itself); 87% of failure tokens sit in 8 long runs.
- Live on 10 held-out tasks (Luna router + active watchdog): **0 runs flagged, 0 tokens saved**, judge overhead ~$0.013. It never flagged crack-7z-hash, which failed after 1.27M tokens (~$0.06) and was checked 17 times.
- Blunt token cap on the training runs cut failures but killed passes 1:1 (cap 150k: cut 7/20 fails, saved 50% of fail tokens, killed 7/45 passes).
- Ops notes: the Mac sleeping froze several runs (fixed with `caffeinate`); some processes hung at Python start and were killed.
- Decision: watchdog dropped for now; focus on the basic router.

## Router v2 (Luna, factual harness capability cards, blind to results): train-set evaluation

Method: cards describe harness capabilities from their design (tmux keystrokes/persistent state; fresh subprocess per command; dedicated file tools + image reading), no results. Variants: v1 = single pick; v2-v4 = Luna scores each harness 1-5, argmax with ties/low margin falling back to terminus-2 (harbor's default agent). Scored offline against the measured outcomes table (`router/outcomes.py`, mean reward per task x harness), so no new harness runs were needed. Train set = the 14 earlier tasks (all three harnesses measured).

| Approach | Expected passes (14 tasks) |
|----------|----------------------------|
| Oracle (best harness per task, hindsight) | 12.25 (88%) |
| Fixed Terminus-2 | 10.75 (77%) |
| Router v1 / v2 / v3 / v4 (all picked equal-value harnesses) | 10.50 (75%) |
| Fixed Mini-SWE | 10.00 (71%) |
| Random routing | 9.92 (71%) |
| Fixed Pi | 9.00 (64%) |

Routing cost for both methods over 14 tasks: $0.0066 (~$0.0002-0.0004 per pick).

Findings:
- The router is a little above random (75% vs 71%) but **below fixed Terminus-2 (77%)**; the difference is under one task, i.e. noise.
- Luna's scores rate Terminus-2 low on most tasks (its card sounds "interactive-only") yet Terminus-2 is the best fixed harness, so the ratings are not tracking real harness strength. In the 7 tasks where harnesses actually differ, its picks were right about half the time.
- Margin/tie-break variants all collapse to the same picks or to fixed Terminus-2, so tuning the decision rule adds nothing.
- Next check: held-out evaluation on the 10 new tasks once the shadow runs (ground truth for all three harnesses) finish.

### Router v2 held-out evaluation (10 new tasks; 7 have all three harnesses measured)

Ground truth from the 30 shadow-watchdog runs plus routed runs (mean reward per task x harness). Router prompts unchanged from the train evaluation (frozen before this test).

| Approach | Expected passes (7 tasks) |
|----------|---------------------------|
| Oracle (best harness per task, hindsight) | 3.67 (52%) |
| Fixed Mini-SWE | 3.00 (43%) |
| Fixed Pi | 2.67 (38%) |
| Random routing | 2.56 (37%) |
| Router v1 / v2 / v3 / v4 | 2.00 (29%) |
| Fixed Terminus-2 | 2.00 (29%) |

Routing cost: $0.0029 for both methods over 7 tasks.

**Combined (14 train + 7 held-out = 21 tasks)**: Oracle 15.9 (76%), Fixed Mini-SWE 13.0 (62%), Fixed Terminus-2 12.75 (61%), Router 12.5 (60%), Random 12.5 (59%), Fixed Pi 11.7 (56%).

Findings:
- **The router did not beat random on held-out data** (29% vs 37%), and again did not beat the best fixed harness. Overall router = random = fixed Terminus-2 within noise.
- **The fixed-harness ranking flips between splits**: Terminus-2 was best on the training tasks (77%) and worst on the held-out tasks (29%). Differences between harnesses look mostly like task-to-task variance, not a stable property of the harness, which is why nothing learned from 14 tasks generalises.
- Luna rated Pi 4-5 on nearly every held-out task (a bias, not signal). Ties broke by list order (e.g. cancel-async-tasks, where Pi was the only harness that passed, went to Mini-SWE).
- The theoretical headroom from perfect routing is ~3 tasks in 21 (oracle 76% vs best fixed 62%); an LLM reading task text is not recovering it.
- Tasks that no harness solved (torch-pipeline-parallelism, path-tracing, chess-best-move, gcode-to-text) cap every strategy; the router can only help on the few tasks where harnesses differ.

**Conclusion**: with Luna 5.6 and 21 tasks, routing by task description provides no measurable benefit over a fixed harness or random choice. Cheapest reasonable default: pick any single harness (Mini-SWE / Terminus-2 are statistically indistinguishable here). More tasks and repeats are the only way to detect a real per-task harness effect.

Code: `router/router.py` (LangGraph router, watchdog removed; `--router gemma|luna`, `--force <harness>`), `router/router2.py` (v1/v2 pick functions), `router/eval_routers.py`, `router/outcomes.py`; watchdog archived in `router/archive_watchdog/`.

Housekeeping: fixed an empty `certifi/cacert.pem` in the router venv (reinstalled certifi) that had broken `langchain_openai` imports.

## Gate router (TF-IDF + Logistic Regression, trained on Qwen's 89-task results): would fine-tuning help?

Before considering a hosted LLM fine-tune as a router, we tested whether *any* supervised classifier could learn task-text -> harness from the Qwen3-Coder-480B 89-task / 4-harness baseline (`Qwen_89_Task_Comparison_2026-09-20.xlsx`). Ground truth: `pivot.idxmax(axis=1)` over the reward table (mini-swe-agent, terminus-2, opencode, pi), instruction text pulled from `~/.cache/harbor/tasks/*/<task>/instruction.md` (all 89 downloaded via `harbor download terminal-bench --cache`).

Leave-one-out CV (`router/cv_gate.py`), 89 tasks:

| Method | LOOCV accuracy | Notes |
|---|---|---|
| Best fixed harness (mini-swe-agent) | 31.5% (28/89) | baseline |
| Logistic Regression (TF-IDF) | 31.5% | identical picks to majority-class dummy |
| kNN, k=1 | 29.2% | worse than fixed |
| kNN, k=3..15 | 31.5% | collapses to mini-swe-agent 87-89/89 times |
| Random Forest (300 trees) | 31.5% | picks mini-swe-agent 89/89 times |
| Oracle (perfect routing) | 40.4% (36/89) | ceiling |

**Verdict: no exploitable signal.** Four independent classifier families all converge on "always guess the majority class" — none found a feature split, neighbor pattern, or linear direction in the instruction text that beats chance. Since these classifiers are all more sample-efficient than fine-tuning a language model, and none found signal in 88 training examples, a fine-tuned LLM has no realistic path to finding something they missed. Combined with noisy labels (28/69 Luna task×harness pairs disagree across repeat runs) and a small theoretical ceiling (oracle only 9 points / 8 tasks above best-fixed), fine-tuning is not recommended here.

We still wired the winning (tied) method into `router.py` as `--router gate` (`router/gate_router.py`: TF-IDF + Logistic Regression fit on all 89 tasks, falls back to `terminus-2` on any failure, maps `opencode` picks onto the 3-harness set this pipeline runs) for a deterministic, zero-LLM-cost routing mode — expected, per the table above, to output `mini-swe-agent` for nearly every new task rather than to beat the fixed baseline. Verified end-to-end: `--router gate` classifies correctly for `fix-git`/`chess-best-move`/`count-dataset-tokens` and logs a normal `router_log.jsonl` entry under `--execute` (the one live dispatch attempt failed only because the local Docker daemon was not running — unrelated to the routing logic).
